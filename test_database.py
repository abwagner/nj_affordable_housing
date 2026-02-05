#!/usr/bin/env python3
"""
Tests for the database module.
Uses in-memory SQLite for speed and isolation.
"""

import tempfile
import unittest
from pathlib import Path

from database import (
    DEFAULT_DB_PATH,
    get_connection,
    init_database,
    insert_municipality,
    get_municipality,
    get_all_municipalities,
    update_municipality_website,
    bulk_insert_municipalities,
    insert_commitment,
    insert_commitment_if_new,
    get_commitments_by_municipality,
    get_all_commitments,
    record_scraped_page,
    is_page_scraped,
    get_database_stats,
)


class TestDatabase(unittest.TestCase):
    """Tests for database operations."""

    def setUp(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_database_creates_tables(self):
        """Test that init_database creates all required tables."""
        stats = get_database_stats(self.db_path)
        self.assertIn("municipalities", stats)
        self.assertIn("commitments", stats)
        self.assertIn("status_updates", stats)
        self.assertIn("news_articles", stats)
        self.assertIn("imagery_analyses", stats)
        self.assertIn("scraped_pages", stats)

    def test_insert_and_get_municipality(self):
        """Test inserting and retrieving a municipality."""
        muni_id = insert_municipality(
            "Test Town",
            county="Test County",
            official_website="https://testtown.gov",
            population=10000,
            db_path=self.db_path,
        )
        self.assertIsInstance(muni_id, int)
        self.assertGreater(muni_id, 0)

        muni = get_municipality(municipality_id=muni_id, db_path=self.db_path)
        self.assertIsNotNone(muni)
        self.assertEqual(muni["name"], "Test Town")
        self.assertEqual(muni["county"], "Test County")
        self.assertEqual(muni["official_website"], "https://testtown.gov")
        self.assertEqual(muni["population"], 10000)

    def test_get_municipality_by_name(self):
        """Test retrieving municipality by name."""
        insert_municipality("Newark", official_website="https://newarknj.gov", db_path=self.db_path)
        muni = get_municipality(name="Newark", db_path=self.db_path)
        self.assertIsNotNone(muni)
        self.assertEqual(muni["name"], "Newark")

    def test_insert_municipality_duplicate_returns_existing_id(self):
        """Test that inserting duplicate municipality returns existing ID."""
        # Must include county since UNIQUE constraint is on (name, county)
        id1 = insert_municipality("Jersey City", county="Hudson", db_path=self.db_path)
        id2 = insert_municipality("Jersey City", county="Hudson", db_path=self.db_path)
        self.assertEqual(id1, id2)

    def test_bulk_insert_municipalities(self):
        """Test bulk insert of municipalities."""
        municipalities = [
            {"name": "Town A", "official_website": "https://towna.gov"},
            {"name": "Town B", "official_website": "https://townb.gov"},
            {"name": "Town C", "official_website": "https://townc.gov"},
        ]
        count = bulk_insert_municipalities(municipalities, db_path=self.db_path)
        self.assertEqual(count, 3)

        all_munis = get_all_municipalities(self.db_path)
        self.assertEqual(len(all_munis), 3)

    def test_bulk_insert_upserts_existing_website(self):
        """Test that re-running bulk_insert updates existing municipalities' websites."""
        # Must include county since UNIQUE constraint is on (name, county)
        bulk_insert_municipalities(
            [{"name": "Town X", "county": "Test County", "official_website": "https://old-website.gov"}],
            db_path=self.db_path,
        )
        muni = get_municipality(name="Town X", county="Test County", db_path=self.db_path)
        self.assertEqual(muni["official_website"], "https://old-website.gov")

        # Re-run with updated website
        bulk_insert_municipalities(
            [{"name": "Town X", "county": "Test County", "official_website": "https://new-website.gov"}],
            db_path=self.db_path,
        )
        muni = get_municipality(name="Town X", county="Test County", db_path=self.db_path)
        self.assertEqual(muni["official_website"], "https://new-website.gov")

    def test_update_municipality_website(self):
        """Test updating a municipality's website."""
        insert_municipality("Paterson", official_website="https://old.gov", db_path=self.db_path)
        success = update_municipality_website("Paterson", "https://patersonnj.gov", db_path=self.db_path)
        self.assertTrue(success)

        muni = get_municipality(name="Paterson", db_path=self.db_path)
        self.assertEqual(muni["official_website"], "https://patersonnj.gov")

    def test_insert_and_get_commitment(self):
        """Test inserting and retrieving commitments."""
        muni_id = insert_municipality("Elizabeth", official_website="https://elizabethnj.org", db_path=self.db_path)
        commit_id = insert_commitment(
            municipality_id=muni_id,
            commitment_type="COAH",
            total_units=50,
            deadline="2028",
            source_document_url="https://example.com/doc.pdf",
            db_path=self.db_path,
        )
        self.assertIsInstance(commit_id, int)
        self.assertGreater(commit_id, 0)

        commitments = get_commitments_by_municipality(municipality_id=muni_id, db_path=self.db_path)
        self.assertEqual(len(commitments), 1)
        self.assertEqual(commitments[0]["commitment_type"], "COAH")
        self.assertEqual(commitments[0]["total_units"], 50)

    def test_get_commitments_by_municipality_name(self):
        """Test getting commitments by municipality name."""
        insert_municipality("Woodbridge", db_path=self.db_path)
        muni = get_municipality(name="Woodbridge", db_path=self.db_path)
        insert_commitment(
            municipality_id=muni["id"],
            total_units=100,
            db_path=self.db_path,
        )
        commitments = get_commitments_by_municipality(municipality_name="Woodbridge", db_path=self.db_path)
        self.assertEqual(len(commitments), 1)

    def test_record_and_check_scraped_page(self):
        """Test recording and checking scraped pages."""
        self.assertFalse(is_page_scraped("https://example.com/page1", db_path=self.db_path))

        record_scraped_page("https://example.com/page1", page_type="planning", db_path=self.db_path)
        self.assertTrue(is_page_scraped("https://example.com/page1", db_path=self.db_path))

    def test_record_scraped_page_without_municipality_id(self):
        """Test that record_scraped_page works without municipality_id."""
        page_id = record_scraped_page(
            "https://example.com/page2",
            page_type="housing",
            db_path=self.db_path,
        )
        self.assertIsInstance(page_id, int)

    def test_insert_commitment_if_new_skips_duplicates(self):
        """Test that insert_commitment_if_new skips duplicate commitments."""
        muni_id = insert_municipality("Dedup Town", official_website="https://dedup.gov", db_path=self.db_path)
        source_url = "https://example.com/housing-plan.pdf"

        id1 = insert_commitment_if_new(
            municipality_id=muni_id,
            total_units=50,
            source_document_url=source_url,
            db_path=self.db_path,
        )
        self.assertIsNotNone(id1)

        id2 = insert_commitment_if_new(
            municipality_id=muni_id,
            total_units=50,
            source_document_url=source_url,
            db_path=self.db_path,
        )
        self.assertIsNone(id2)

        commitments = get_commitments_by_municipality(municipality_id=muni_id, db_path=self.db_path)
        self.assertEqual(len(commitments), 1)

    def test_get_database_stats(self):
        """Test database statistics."""
        insert_municipality("Town X", official_website="https://townx.gov", db_path=self.db_path)
        stats = get_database_stats(self.db_path)
        self.assertEqual(stats["municipalities"], 1)
        self.assertEqual(stats["municipalities_with_websites"], 1)
        self.assertEqual(stats["commitments"], 0)
        self.assertEqual(stats["total_committed_units"], 0)


if __name__ == "__main__":
    unittest.main()
