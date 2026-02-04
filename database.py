#!/usr/bin/env python3
"""
Database module for NJ Affordable Housing Tracker.

Provides SQLite database setup and operations for tracking municipalities,
affordable housing commitments, status updates, news articles, and imagery analysis.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import structlog

LOGGER = structlog.get_logger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent / "nj_affordable_housing.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory for dict-like access."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Initialize the database with all required tables."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Municipalities table (from Stage 1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS municipalities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            county TEXT,
            official_website TEXT,
            population INTEGER,
            last_scraped TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Housing Commitments table (Stage 2)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            municipality_id INTEGER NOT NULL,
            commitment_type TEXT,
            total_units INTEGER,
            low_income_units INTEGER,
            moderate_income_units INTEGER,
            senior_units INTEGER,
            family_units INTEGER,
            deadline DATE,
            developer TEXT,
            project_name TEXT,
            location_address TEXT,
            location_lat REAL,
            location_lng REAL,
            source_document_url TEXT,
            source_document_type TEXT,
            date_announced DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (municipality_id) REFERENCES municipalities(id)
        )
    """)

    # Create index for faster lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_commitments_municipality
        ON commitments(municipality_id)
    """)

    # Status Updates table (Stage 3 & 4)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            source_type TEXT,
            source_url TEXT,
            notes TEXT,
            verified_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commitment_id) REFERENCES commitments(id)
        )
    """)

    # Create index for status lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status_commitment
        ON status_updates(commitment_id)
    """)

    # News Articles table (Stage 3)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id INTEGER,
            municipality_id INTEGER,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            source_name TEXT,
            publish_date DATE,
            extracted_status TEXT,
            summary TEXT,
            full_text TEXT,
            relevance_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commitment_id) REFERENCES commitments(id),
            FOREIGN KEY (municipality_id) REFERENCES municipalities(id)
        )
    """)

    # Create indexes for news articles
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_commitment
        ON news_articles(commitment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_municipality
        ON news_articles(municipality_id)
    """)

    # Imagery Analysis table (Stage 4)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS imagery_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id INTEGER NOT NULL,
            imagery_date DATE NOT NULL,
            imagery_source TEXT,
            construction_detected INTEGER,
            confidence_score REAL,
            building_footprint_area REAL,
            change_from_baseline INTEGER,
            image_url TEXT,
            baseline_image_url TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commitment_id) REFERENCES commitments(id)
        )
    """)

    # Create index for imagery lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_imagery_commitment
        ON imagery_analyses(commitment_id)
    """)

    # Scraped Pages table (for tracking what we've already scraped)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraped_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            municipality_id INTEGER,
            url TEXT NOT NULL,
            page_type TEXT,
            content_hash TEXT,
            last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            FOREIGN KEY (municipality_id) REFERENCES municipalities(id)
        )
    """)

    # Create index for scraped pages
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scraped_url
        ON scraped_pages(url)
    """)

    # Official Obligations table (from NJ DCA Fourth Round data)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS official_obligations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            municipality_id INTEGER NOT NULL UNIQUE,
            fips_code TEXT,
            dca_municode TEXT,
            county TEXT,
            region INTEGER,
            present_need INTEGER,
            prospective_need INTEGER,
            total_obligation INTEGER,
            qualified_urban_aid INTEGER DEFAULT 0,
            total_households INTEGER,
            data_source TEXT,
            calculation_year INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (municipality_id) REFERENCES municipalities(id)
        )
    """)

    # Create index for official obligations
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_obligations_county
        ON official_obligations(county)
    """)

    conn.commit()
    conn.close()
    LOGGER.info(f"Database initialized at {db_path}")


# ============================================================================
# Municipality Operations
# ============================================================================

def insert_municipality(name: str, county: str = None, official_website: str = None,
                       population: int = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert a new municipality and return its ID, or existing ID if already present."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO municipalities (name, county, official_website, population)
            VALUES (?, ?, ?, ?)
        """, (name, county, official_website, population))
        conn.commit()
        municipality_id = cursor.lastrowid
        LOGGER.info(f"Inserted municipality: {name} (ID: {municipality_id})")
        return municipality_id
    except sqlite3.IntegrityError:
        # Municipality already exists, get its ID
        cursor.execute("SELECT id FROM municipalities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"IntegrityError on insert but municipality '{name}' not found")
        return row['id']
    finally:
        conn.close()


def get_municipality(name: str = None, municipality_id: int = None,
                    db_path: Path = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Get a municipality by name or ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if municipality_id:
        cursor.execute("SELECT * FROM municipalities WHERE id = ?", (municipality_id,))
    elif name:
        cursor.execute("SELECT * FROM municipalities WHERE name = ?", (name,))
    else:
        conn.close()
        return None

    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_municipalities(db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Get all municipalities."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM municipalities ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_municipality_website(name: str, website: str,
                                db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Update a municipality's official website."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE municipalities
        SET official_website = ?, updated_at = CURRENT_TIMESTAMP
        WHERE name = ?
    """, (website, name))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success


def bulk_insert_municipalities(municipalities: List[Dict[str, Any]],
                               db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    Bulk insert or update municipalities.
    Uses UPSERT: inserts new municipalities, updates official_website for existing ones.
    Returns count of rows inserted or updated.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    count = 0
    for muni in municipalities:
        try:
            cursor.execute("""
                INSERT INTO municipalities (name, county, official_website, population)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    official_website = COALESCE(excluded.official_website, official_website),
                    county = COALESCE(excluded.county, county),
                    population = COALESCE(excluded.population, population),
                    updated_at = CURRENT_TIMESTAMP
            """, (muni.get('name'), muni.get('county'),
                  muni.get('official_website'), muni.get('population')))
            if cursor.rowcount > 0:
                count += 1
        except Exception as e:
            LOGGER.error(f"Error upserting {muni.get('name')}: {e}")

    conn.commit()
    conn.close()
    LOGGER.info(f"Bulk upserted {count} municipalities")
    return count


# ============================================================================
# Commitment Operations
# ============================================================================

def _commitment_exists(municipality_id: int, source_document_url: Optional[str],
                      db_path: Path) -> bool:
    """Check if a commitment from this source already exists for the municipality."""
    if not source_document_url:
        return False
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM commitments
        WHERE municipality_id = ? AND source_document_url = ?
    """, (municipality_id, source_document_url))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def insert_commitment(municipality_id: int, commitment_type: str = None,
                     total_units: int = None, low_income_units: int = None,
                     moderate_income_units: int = None, deadline: str = None,
                     developer: str = None, project_name: str = None,
                     location_address: str = None, source_document_url: str = None,
                     source_document_type: str = None, date_announced: str = None,
                     notes: str = None, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert a new housing commitment and return its ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO commitments (
            municipality_id, commitment_type, total_units, low_income_units,
            moderate_income_units, deadline, developer, project_name,
            location_address, source_document_url, source_document_type,
            date_announced, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (municipality_id, commitment_type, total_units, low_income_units,
          moderate_income_units, deadline, developer, project_name,
          location_address, source_document_url, source_document_type,
          date_announced, notes))

    conn.commit()
    commitment_id = cursor.lastrowid
    conn.close()
    LOGGER.info(f"Inserted commitment ID: {commitment_id} for municipality ID: {municipality_id}")
    return commitment_id


def insert_commitment_if_new(municipality_id: int, commitment_type: str = None,
                             total_units: int = None, low_income_units: int = None,
                             moderate_income_units: int = None, deadline: str = None,
                             developer: str = None, project_name: str = None,
                             location_address: str = None, source_document_url: str = None,
                             source_document_type: str = None, date_announced: str = None,
                             notes: str = None, db_path: Path = DEFAULT_DB_PATH) -> Optional[int]:
    """
    Insert a commitment only if one from the same source doesn't already exist.
    Returns commitment ID if inserted, or None if skipped (duplicate).
    """
    if _commitment_exists(municipality_id, source_document_url, db_path):
        LOGGER.debug(f"Skipping duplicate commitment: municipality_id={municipality_id}, "
                     f"source={source_document_url}")
        return None
    return insert_commitment(
        municipality_id=municipality_id,
        commitment_type=commitment_type,
        total_units=total_units,
        low_income_units=low_income_units,
        moderate_income_units=moderate_income_units,
        deadline=deadline,
        developer=developer,
        project_name=project_name,
        location_address=location_address,
        source_document_url=source_document_url,
        source_document_type=source_document_type,
        date_announced=date_announced,
        notes=notes,
        db_path=db_path,
    )


def get_commitments_by_municipality(municipality_id: int = None, municipality_name: str = None,
                                    db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Get all commitments for a municipality."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if municipality_id:
        cursor.execute("""
            SELECT c.*, m.name as municipality_name
            FROM commitments c
            JOIN municipalities m ON c.municipality_id = m.id
            WHERE c.municipality_id = ?
            ORDER BY c.date_announced DESC
        """, (municipality_id,))
    elif municipality_name:
        cursor.execute("""
            SELECT c.*, m.name as municipality_name
            FROM commitments c
            JOIN municipalities m ON c.municipality_id = m.id
            WHERE m.name = ?
            ORDER BY c.date_announced DESC
        """, (municipality_name,))
    else:
        conn.close()
        return []

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_commitments(db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Get all commitments with municipality names."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*, m.name as municipality_name
        FROM commitments c
        JOIN municipalities m ON c.municipality_id = m.id
        ORDER BY m.name, c.date_announced DESC
    """)

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================================================
# Status Update Operations
# ============================================================================

def insert_status_update(commitment_id: int, status: str, source_type: str = None,
                        source_url: str = None, notes: str = None,
                        verified_date: str = None,
                        db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert a new status update and return its ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO status_updates (commitment_id, status, source_type, source_url, notes, verified_date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (commitment_id, status, source_type, source_url, notes, verified_date))

    conn.commit()
    status_id = cursor.lastrowid
    conn.close()
    return status_id


def get_latest_status(commitment_id: int,
                     db_path: Path = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Get the most recent status update for a commitment."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM status_updates
        WHERE commitment_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (commitment_id,))

    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================================================
# News Article Operations
# ============================================================================

def insert_news_article(title: str, url: str, municipality_id: int = None,
                       commitment_id: int = None, source_name: str = None,
                       publish_date: str = None, extracted_status: str = None,
                       summary: str = None, full_text: str = None,
                       relevance_score: float = None,
                       db_path: Path = DEFAULT_DB_PATH) -> Optional[int]:
    """Insert a new news article and return its ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO news_articles (
                title, url, municipality_id, commitment_id, source_name,
                publish_date, extracted_status, summary, full_text, relevance_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, url, municipality_id, commitment_id, source_name,
              publish_date, extracted_status, summary, full_text, relevance_score))

        conn.commit()
        article_id = cursor.lastrowid
        conn.close()
        return article_id
    except sqlite3.IntegrityError:
        # Article URL already exists
        conn.close()
        return None


# ============================================================================
# Scraped Pages Operations
# ============================================================================

def record_scraped_page(url: str, municipality_id: int = None, page_type: str = None,
                       content_hash: str = None, success: bool = True,
                       error_message: str = None,
                       db_path: Path = DEFAULT_DB_PATH) -> int:
    """Record a scraped page to avoid re-scraping."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO scraped_pages
        (municipality_id, url, page_type, content_hash, last_scraped, success, error_message)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
    """, (municipality_id, url, page_type, content_hash, 1 if success else 0, error_message))

    conn.commit()
    page_id = cursor.lastrowid
    conn.close()
    return page_id


def is_page_scraped(url: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Check if a page has already been scraped."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM scraped_pages WHERE url = ?", (url,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


# ============================================================================
# Official Obligations Operations
# ============================================================================

def upsert_official_obligation(
    municipality_id: int,
    present_need: int = None,
    prospective_need: int = None,
    total_obligation: int = None,
    fips_code: str = None,
    dca_municode: str = None,
    county: str = None,
    region: int = None,
    qualified_urban_aid: int = 0,
    total_households: int = None,
    data_source: str = None,
    calculation_year: int = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """Insert or update an official obligation record."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO official_obligations (
            municipality_id, fips_code, dca_municode, county, region,
            present_need, prospective_need, total_obligation,
            qualified_urban_aid, total_households, data_source, calculation_year
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipality_id) DO UPDATE SET
            fips_code = excluded.fips_code,
            dca_municode = excluded.dca_municode,
            county = excluded.county,
            region = excluded.region,
            present_need = excluded.present_need,
            prospective_need = excluded.prospective_need,
            total_obligation = excluded.total_obligation,
            qualified_urban_aid = excluded.qualified_urban_aid,
            total_households = excluded.total_households,
            data_source = excluded.data_source,
            calculation_year = excluded.calculation_year,
            updated_at = CURRENT_TIMESTAMP
    """, (municipality_id, fips_code, dca_municode, county, region,
          present_need, prospective_need, total_obligation,
          qualified_urban_aid, total_households, data_source, calculation_year))

    conn.commit()
    obligation_id = cursor.lastrowid
    conn.close()
    return obligation_id


def get_official_obligation(municipality_id: int = None, municipality_name: str = None,
                           db_path: Path = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Get official obligation for a municipality."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if municipality_id:
        cursor.execute("""
            SELECT o.*, m.name as municipality_name
            FROM official_obligations o
            JOIN municipalities m ON o.municipality_id = m.id
            WHERE o.municipality_id = ?
        """, (municipality_id,))
    elif municipality_name:
        cursor.execute("""
            SELECT o.*, m.name as municipality_name
            FROM official_obligations o
            JOIN municipalities m ON o.municipality_id = m.id
            WHERE m.name = ?
        """, (municipality_name,))
    else:
        conn.close()
        return None

    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_official_obligations(db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Get all official obligations with municipality names."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT o.*, m.name as municipality_name, m.official_website
        FROM official_obligations o
        JOIN municipalities m ON o.municipality_id = m.id
        ORDER BY o.total_obligation DESC
    """)

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_obligations_by_county(county: str, db_path: Path = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Get all official obligations for a specific county."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT o.*, m.name as municipality_name, m.official_website
        FROM official_obligations o
        JOIN municipalities m ON o.municipality_id = m.id
        WHERE o.county = ?
        ORDER BY o.total_obligation DESC
    """, (county,))

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================================================
# Summary/Stats Operations
# ============================================================================

def get_database_stats(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, int]:
    """Get counts of all records in the database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    stats = {}
    tables = ['municipalities', 'commitments', 'status_updates', 'news_articles',
              'imagery_analyses', 'scraped_pages', 'official_obligations']

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            stats[table] = cursor.fetchone()['count']
        except sqlite3.OperationalError:
            stats[table] = 0

    # Additional stats
    cursor.execute("""
        SELECT COUNT(*) as count FROM municipalities WHERE official_website IS NOT NULL
    """)
    stats['municipalities_with_websites'] = cursor.fetchone()['count']

    cursor.execute("""
        SELECT SUM(total_units) as total FROM commitments
    """)
    result = cursor.fetchone()['total']
    stats['total_committed_units'] = result if result else 0

    # Official obligations stats
    try:
        cursor.execute("""
            SELECT SUM(total_obligation) as total FROM official_obligations
        """)
        result = cursor.fetchone()['total']
        stats['total_official_obligation'] = result if result else 0
    except sqlite3.OperationalError:
        stats['total_official_obligation'] = 0

    conn.close()
    return stats


# ============================================================================
# Main / CLI
# ============================================================================

if __name__ == "__main__":
    from log_config import configure_logging
    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="NJ Affordable Housing Database")
    parser.add_argument("--init", action="store_true", help="Initialize the database")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH),
                       help="Database file path")

    args = parser.parse_args()
    db_path = Path(args.db)

    if args.init:
        init_database(db_path)
        LOGGER.info("Database initialized", path=str(db_path))

    if args.stats:
        if not db_path.exists():
            LOGGER.error("Database not found", path=str(db_path), hint="Run with --init first")
        else:
            stats = get_database_stats(db_path)
            LOGGER.info("Database statistics", **stats)
