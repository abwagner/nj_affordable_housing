#!/usr/bin/env python3
"""
Load NJ DCA Fourth Round (2025-2035) Affordable Housing Obligations into Database.

This script loads official affordable housing obligation data from the NJ Department
of Community Affairs Excel workbook into the local SQLite database.

Data source: https://www.nj.gov/dca/dlps/4th_Round_Numbers.shtml
"""

from pathlib import Path
from typing import Dict, Optional
import structlog

import pandas as pd

from database import (
    init_database, get_connection, get_municipality,
    insert_municipality, upsert_official_obligation,
    get_database_stats, DEFAULT_DB_PATH
)

LOGGER = structlog.get_logger(__name__)

# Path to the DCA Excel workbook
DCA_WORKBOOK_PATH = Path(__file__).parent / "data" / "FourthRoundCalculation_Workbook.xlsx"


def normalize_municipality_name(name: str) -> str:
    """
    Normalize municipality name for matching.
    The DCA data uses full formal names (e.g., "Newark city", "Edison township")
    while our database may have variations.
    """
    if not name:
        return ""

    # Convert to title case and clean up
    name = name.strip()

    # Common suffixes in DCA data that may differ in our database
    suffixes_to_normalize = [
        (' city', ''),
        (' township', ' Township'),
        (' borough', ' Borough'),
        (' town', ' Town'),
        (' village', ' Village'),
    ]

    name_lower = name.lower()
    for old, new in suffixes_to_normalize:
        if name_lower.endswith(old):
            # Keep the capitalization style from original
            base = name[:-len(old)]
            name = base + new
            break

    return name


def find_municipality_id(name: str, county: str, db_path: Path) -> Optional[int]:
    """
    Find municipality ID by name, trying various name formats.
    Returns municipality ID if found, None otherwise.
    """
    # Try exact match first
    muni = get_municipality(name=name, db_path=db_path)
    if muni:
        return muni['id']

    # Try normalized name
    normalized = normalize_municipality_name(name)
    muni = get_municipality(name=normalized, db_path=db_path)
    if muni:
        return muni['id']

    # Try without suffix
    for suffix in [' city', ' township', ' borough', ' town', ' village',
                   ' City', ' Township', ' Borough', ' Town', ' Village']:
        if name.endswith(suffix):
            base_name = name[:-len(suffix)]
            muni = get_municipality(name=base_name, db_path=db_path)
            if muni:
                return muni['id']

    # Try adding Township/Borough suffix (common in NJ)
    for suffix in [' Township', ' Borough']:
        muni = get_municipality(name=name + suffix, db_path=db_path)
        if muni:
            return muni['id']

    return None


def load_dca_obligations(
    excel_path: Path = DCA_WORKBOOK_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    create_missing: bool = True
) -> Dict[str, int]:
    """
    Load DCA Fourth Round obligations from Excel into database.

    Args:
        excel_path: Path to the DCA Excel workbook
        db_path: Path to the SQLite database
        create_missing: If True, create municipality records for those not found

    Returns:
        Dictionary with counts: loaded, skipped, created
    """
    if not excel_path.exists():
        raise FileNotFoundError(f"DCA workbook not found: {excel_path}")

    # Ensure database is initialized with new schema
    init_database(db_path)

    LOGGER.info("Loading DCA Fourth Round obligations", excel_path=str(excel_path))

    # Load Excel data
    df = pd.read_excel(excel_path, sheet_name='Final Summary', header=2)

    # Strip whitespace from column names
    df.columns = df.columns.str.strip()

    # Get relevant columns
    cols = [
        'County Subdivision FIPS Code', 'DCA Municode', 'Municipality',
        'County', 'Region', 'Present Need', 'Prospective Need',
        'Qualified Urban Aid Municipality', 'Total Households (2020 Census)'
    ]

    # Filter to available columns
    available_cols = [c for c in cols if c in df.columns]
    df_clean = df[available_cols].copy()

    # Remove NaN municipalities and summary rows
    df_clean = df_clean.dropna(subset=['Municipality'])
    df_clean = df_clean[~df_clean['Municipality'].astype(str).str.contains(
        'TOTAL|Region|NaN', case=False, na=False
    )]

    stats = {'loaded': 0, 'skipped': 0, 'created': 0, 'not_found': 0}
    not_found_municipalities = []

    for _, row in df_clean.iterrows():
        muni_name = str(row['Municipality']).strip()
        county = str(row.get('County', '')).strip()

        # Find municipality ID
        muni_id = find_municipality_id(muni_name, county, db_path)

        if muni_id is None:
            if create_missing:
                # Create the municipality
                normalized_name = normalize_municipality_name(muni_name)
                muni_id = insert_municipality(
                    name=normalized_name if normalized_name else muni_name,
                    county=county,
                    db_path=db_path
                )
                stats['created'] += 1
                LOGGER.debug("Created municipality", name=muni_name, id=muni_id)
            else:
                stats['not_found'] += 1
                not_found_municipalities.append(muni_name)
                continue

        # Calculate total obligation
        present_need = int(row.get('Present Need', 0) or 0)
        prospective_need = int(row.get('Prospective Need', 0) or 0)
        total_obligation = present_need + prospective_need

        # Insert/update official obligation
        upsert_official_obligation(
            municipality_id=muni_id,
            fips_code=str(row.get('County Subdivision FIPS Code', '')),
            dca_municode=str(row.get('DCA Municode', '')),
            county=county,
            region=int(row.get('Region', 0) or 0),
            present_need=present_need,
            prospective_need=prospective_need,
            total_obligation=total_obligation,
            qualified_urban_aid=int(row.get('Qualified Urban Aid Municipality', 0) or 0),
            total_households=int(row.get('Total Households (2020 Census)', 0) or 0),
            data_source='NJ DCA Fourth Round Calculations (2024)',
            calculation_year=2025,
            db_path=db_path
        )

        stats['loaded'] += 1

    if not_found_municipalities:
        LOGGER.warning(
            "Municipalities not found in database",
            count=len(not_found_municipalities),
            sample=not_found_municipalities[:10]
        )

    LOGGER.info(
        "DCA obligations loaded",
        loaded=stats['loaded'],
        created=stats['created'],
        not_found=stats['not_found']
    )

    return stats


def main():
    """Main function to load DCA obligations."""
    from log_config import configure_logging
    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(
        description="Load NJ DCA Fourth Round Affordable Housing Obligations"
    )
    parser.add_argument(
        "--excel", type=str, default=str(DCA_WORKBOOK_PATH),
        help="Path to DCA Excel workbook"
    )
    parser.add_argument(
        "--db", type=str, default=str(DEFAULT_DB_PATH),
        help="Database file path"
    )
    parser.add_argument(
        "--no-create", action="store_true",
        help="Don't create missing municipalities"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show database statistics after loading"
    )

    args = parser.parse_args()

    excel_path = Path(args.excel)
    db_path = Path(args.db)

    # Load obligations
    stats = load_dca_obligations(
        excel_path=excel_path,
        db_path=db_path,
        create_missing=not args.no_create
    )

    LOGGER.info("Load complete", **stats)

    if args.stats:
        db_stats = get_database_stats(db_path)
        LOGGER.info("Database statistics", **db_stats)


if __name__ == "__main__":
    main()
