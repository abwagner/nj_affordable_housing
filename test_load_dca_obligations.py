#!/usr/bin/env python3
"""
Tests for load_dca_obligations module.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from load_dca_obligations import (
    normalize_municipality_name,
    find_municipality_id,
    load_dca_obligations,
    DCA_WORKBOOK_PATH
)
from database import init_database, insert_municipality, get_official_obligation


class TestNormalizeMunicipalityName(unittest.TestCase):
    """Tests for normalize_municipality_name function."""

    def test_empty_string(self):
        """Test empty string returns empty."""
        self.assertEqual(normalize_municipality_name(""), "")

    def test_none_handling(self):
        """Test None input returns empty string."""
        self.assertEqual(normalize_municipality_name(None), "")

    def test_city_suffix(self):
        """Test 'city' suffix normalization."""
        self.assertEqual(normalize_municipality_name("Newark city"), "Newark")
        self.assertEqual(normalize_municipality_name("Jersey City"), "Jersey")

    def test_township_suffix(self):
        """Test 'township' suffix normalization."""
        self.assertEqual(normalize_municipality_name("Edison township"), "Edison Township")
        self.assertEqual(normalize_municipality_name("Wayne Township"), "Wayne Township")

    def test_borough_suffix(self):
        """Test 'borough' suffix normalization."""
        self.assertEqual(normalize_municipality_name("Paramus borough"), "Paramus Borough")

    def test_town_suffix(self):
        """Test 'town' suffix normalization."""
        self.assertEqual(normalize_municipality_name("Morristown town"), "Morristown Town")

    def test_village_suffix(self):
        """Test 'village' suffix normalization."""
        self.assertEqual(normalize_municipality_name("Ridgewood village"), "Ridgewood Village")

    def test_whitespace_handling(self):
        """Test whitespace is stripped."""
        self.assertEqual(normalize_municipality_name("  Newark city  "), "Newark")

    def test_no_suffix(self):
        """Test names without suffixes are unchanged."""
        self.assertEqual(normalize_municipality_name("Newark"), "Newark")


class TestFindMunicipalityId(unittest.TestCase):
    """Tests for find_municipality_id function."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)

        # Insert test municipalities
        insert_municipality("Newark", county="Essex", db_path=self.db_path)
        insert_municipality("Edison Township", county="Middlesex", db_path=self.db_path)
        insert_municipality("Paramus Borough", county="Bergen", db_path=self.db_path)

    def tearDown(self):
        """Clean up test database."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_exact_match(self):
        """Test exact name match."""
        muni_id = find_municipality_id("Newark", "Essex", self.db_path)
        self.assertIsNotNone(muni_id)

    def test_normalized_match(self):
        """Test normalized name match."""
        # "Edison township" should match "Edison Township"
        muni_id = find_municipality_id("Edison township", "Middlesex", self.db_path)
        self.assertIsNotNone(muni_id)

    def test_suffix_variations(self):
        """Test matching with different suffix formats."""
        # "Paramus borough" should match "Paramus Borough"
        muni_id = find_municipality_id("Paramus borough", "Bergen", self.db_path)
        self.assertIsNotNone(muni_id)

    def test_no_match(self):
        """Test no match returns None."""
        muni_id = find_municipality_id("NonexistentCity", "FakeCounty", self.db_path)
        self.assertIsNone(muni_id)

    def test_base_name_match(self):
        """Test matching by base name without suffix."""
        # "Newark" should match if we search for "Newark city"
        muni_id = find_municipality_id("Newark city", "Essex", self.db_path)
        self.assertIsNotNone(muni_id)


class TestLoadDCAObligations(unittest.TestCase):
    """Tests for load_dca_obligations function."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)

    def tearDown(self):
        """Clean up test database."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_excel_file(self):
        """Test error when Excel file doesn't exist."""
        fake_path = Path("/nonexistent/file.xlsx")
        with self.assertRaises(FileNotFoundError):
            load_dca_obligations(excel_path=fake_path, db_path=self.db_path)

    @unittest.skipIf(not DCA_WORKBOOK_PATH.exists(), "DCA workbook not downloaded")
    def test_load_with_real_data(self):
        """Integration test with real DCA data."""
        # Pre-populate with some municipalities
        insert_municipality("Newark", county="Essex", db_path=self.db_path)
        insert_municipality("Jersey City", county="Hudson", db_path=self.db_path)

        stats = load_dca_obligations(
            excel_path=DCA_WORKBOOK_PATH,
            db_path=self.db_path,
            create_missing=True
        )

        # Should have loaded some obligations
        self.assertGreater(stats['loaded'], 0)

        # Check Newark has an obligation
        obligation = get_official_obligation(
            municipality_name="Newark",
            db_path=self.db_path
        )
        self.assertIsNotNone(obligation)
        self.assertGreater(obligation['total_obligation'], 0)

    @unittest.skipIf(not DCA_WORKBOOK_PATH.exists(), "DCA workbook not downloaded")
    def test_load_without_creating_missing(self):
        """Test loading without creating missing municipalities."""
        # Only add Newark
        insert_municipality("Newark", county="Essex", db_path=self.db_path)

        stats = load_dca_obligations(
            excel_path=DCA_WORKBOOK_PATH,
            db_path=self.db_path,
            create_missing=False
        )

        # Should have many not found
        self.assertGreater(stats['not_found'], 0)
        # Should have loaded at least Newark
        self.assertGreater(stats['loaded'], 0)


class TestOfficialObligationsDatabaseFunctions(unittest.TestCase):
    """Tests for official obligations database functions."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)

        # Insert test municipality
        self.muni_id = insert_municipality(
            "Test Township",
            county="Test County",
            db_path=self.db_path
        )

    def tearDown(self):
        """Clean up test database."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_upsert_official_obligation_insert(self):
        """Test inserting a new official obligation."""
        from database import upsert_official_obligation

        result = upsert_official_obligation(
            municipality_id=self.muni_id,
            present_need=100,
            prospective_need=200,
            total_obligation=300,
            county="Test County",
            region=1,
            data_source="Test Source",
            calculation_year=2025,
            db_path=self.db_path
        )

        self.assertIsNotNone(result)

        # Verify the data was stored
        obligation = get_official_obligation(
            municipality_id=self.muni_id,
            db_path=self.db_path
        )
        self.assertEqual(obligation['present_need'], 100)
        self.assertEqual(obligation['prospective_need'], 200)
        self.assertEqual(obligation['total_obligation'], 300)
        self.assertEqual(obligation['data_source'], "Test Source")

    def test_upsert_official_obligation_update(self):
        """Test updating an existing official obligation."""
        from database import upsert_official_obligation

        # Insert first
        upsert_official_obligation(
            municipality_id=self.muni_id,
            present_need=100,
            prospective_need=200,
            total_obligation=300,
            db_path=self.db_path
        )

        # Update
        upsert_official_obligation(
            municipality_id=self.muni_id,
            present_need=150,
            prospective_need=250,
            total_obligation=400,
            db_path=self.db_path
        )

        # Verify updated values
        obligation = get_official_obligation(
            municipality_id=self.muni_id,
            db_path=self.db_path
        )
        self.assertEqual(obligation['present_need'], 150)
        self.assertEqual(obligation['prospective_need'], 250)
        self.assertEqual(obligation['total_obligation'], 400)

    def test_get_official_obligation_by_name(self):
        """Test retrieving obligation by municipality name."""
        from database import upsert_official_obligation

        upsert_official_obligation(
            municipality_id=self.muni_id,
            present_need=100,
            total_obligation=100,
            db_path=self.db_path
        )

        obligation = get_official_obligation(
            municipality_name="Test Township",
            db_path=self.db_path
        )

        self.assertIsNotNone(obligation)
        self.assertEqual(obligation['municipality_name'], "Test Township")

    def test_get_official_obligation_not_found(self):
        """Test retrieving non-existent obligation."""
        obligation = get_official_obligation(
            municipality_name="Nonexistent",
            db_path=self.db_path
        )

        self.assertIsNone(obligation)

    def test_get_all_official_obligations(self):
        """Test retrieving all obligations."""
        from database import upsert_official_obligation, get_all_official_obligations

        # Insert multiple
        muni_id2 = insert_municipality("Test Borough", db_path=self.db_path)

        upsert_official_obligation(
            municipality_id=self.muni_id,
            total_obligation=500,
            db_path=self.db_path
        )
        upsert_official_obligation(
            municipality_id=muni_id2,
            total_obligation=300,
            db_path=self.db_path
        )

        obligations = get_all_official_obligations(db_path=self.db_path)

        self.assertEqual(len(obligations), 2)
        # Should be ordered by total_obligation DESC
        self.assertEqual(obligations[0]['total_obligation'], 500)
        self.assertEqual(obligations[1]['total_obligation'], 300)

    def test_get_obligations_by_county(self):
        """Test retrieving obligations by county."""
        from database import upsert_official_obligation, get_obligations_by_county

        upsert_official_obligation(
            municipality_id=self.muni_id,
            county="Test County",
            total_obligation=100,
            db_path=self.db_path
        )

        obligations = get_obligations_by_county("Test County", db_path=self.db_path)

        self.assertEqual(len(obligations), 1)
        self.assertEqual(obligations[0]['county'], "Test County")

        # Test non-existent county
        empty = get_obligations_by_county("Fake County", db_path=self.db_path)
        self.assertEqual(len(empty), 0)


if __name__ == '__main__':
    unittest.main()
