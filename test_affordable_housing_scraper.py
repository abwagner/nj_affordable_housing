#!/usr/bin/env python3
"""
Tests for the affordable housing scraper module.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from affordable_housing_scraper import (
    AffordableHousingScraper,
    load_stage1_results_to_db,
)
from database import init_database, get_all_municipalities, get_commitments_by_municipality


class TestAffordableHousingScraper(unittest.TestCase):
    """Unit tests for AffordableHousingScraper."""

    def setUp(self):
        """Create temporary database and scraper instance."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)
        self.scraper = AffordableHousingScraper(db_path=self.db_path)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_housing_info_no_keywords_returns_empty(self):
        """Page without affordable housing keywords returns empty list."""
        html = "<html><body><p>Generic municipal content about parks and recreation.</p></body></html>"
        result = self.scraper._extract_housing_info(
            html, "https://example.com/page", "Test Town"
        )
        self.assertEqual(result, [])

    def test_extract_housing_info_extracts_unit_count(self):
        """Extracts unit count from page with affordable housing content."""
        html = """
        <html><body>
        <p>The township has committed to 75 affordable housing units as part of
        the settlement agreement. Must be completed by 2028.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com/housing", "Test Township"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].total_units, 75)
        self.assertEqual(result[0].commitment_type, "Settlement Agreement")
        self.assertEqual(result[0].deadline, "2028")

    def test_extract_housing_info_extracts_coah_type(self):
        """Extracts COAH commitment type."""
        html = """
        <html><body>
        <p>This municipality has a COAH obligation of 50 low income housing units.
        The council on affordable housing approved the plan.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com/coah", "Test Borough"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].commitment_type, "COAH")
        self.assertEqual(result[0].total_units, 50)

    def test_extract_housing_info_extracts_mount_laurel(self):
        """Extracts Mount Laurel commitment type."""
        html = """
        <html><body>
        <p>Under Mount Laurel, the borough must provide 30 affordable units.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com/mount-laurel", "Test Town"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].commitment_type, "Mount Laurel")

    def test_extract_housing_info_extracts_deadline(self):
        """Extracts deadline year from various patterns."""
        html = """
        <html><body>
        <p>Total of 100 affordable units must be completed by 2029. Settlement agreement.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com", "Test City"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].deadline, "2029")
        self.assertEqual(result[0].total_units, 100)

    def test_extract_housing_info_extracts_project_name(self):
        """Extracts project name with capitalized development suffix."""
        html = """
        <html><body>
        <p>The Riverside Village development will include 40 affordable housing units.
        Fair Share obligations require completion by 2027.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com", "Test Township"
        )
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0].project_name)
        self.assertIn("Village", result[0].project_name or "")

    def test_extract_housing_info_sanity_check_rejects_large_numbers(self):
        """Rejects unreasonably large unit counts."""
        html = """
        <html><body>
        <p>We have 99999 affordable housing units in our plan. Settlement agreement.</p>
        </body></html>
        """
        result = self.scraper._extract_housing_info(
            html, "https://example.com", "Test"
        )
        # Should still return a commitment but total_units may be None due to sanity check
        if result:
            self.assertLess(result[0].total_units or 0, 10000)

    def test_find_relevant_links_finds_planning_links(self):
        """Finds links with planning/housing keywords."""
        html = """
        <html><body>
        <a href="/planning-board">Planning Board</a>
        <a href="/zoning">Zoning Board</a>
        <a href="/recreation">Recreation</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        links = self.scraper._find_relevant_links(soup, "https://example.gov")
        self.assertGreater(len(links), 0)
        link_types = [l["type"] for l in links]
        self.assertIn("planning board", link_types)
        self.assertIn("zoning board", link_types)

    def test_find_relevant_links_same_domain_only(self):
        """Only includes links on same domain."""
        html = """
        <html><body>
        <a href="/local/planning">Planning Board</a>
        <a href="https://other.gov/planning">External Planning</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        links = self.scraper._find_relevant_links(soup, "https://example.gov")
        urls = [l["url"] for l in links]
        self.assertTrue(all("example.gov" in u for u in urls))
        self.assertFalse(any("other.gov" in u for u in urls))

    def test_find_document_links_finds_relevant_pdfs(self):
        """Finds PDF links with affordable housing keywords."""
        html = """
        <html><body>
        <a href="/docs/affordable-housing-plan.pdf">Affordable Housing Plan</a>
        <a href="/docs/budget.pdf">Budget 2024</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        docs = self.scraper._find_document_links(soup, "https://example.gov")
        self.assertEqual(len(docs), 1)
        self.assertIn(".pdf", docs[0]["url"])

    def test_scrape_municipality_with_mocked_fetch(self):
        """Scrapes municipality when _fetch_page is mocked."""
        html = """
        <html><body>
        <a href="/planning">Planning Board</a>
        <p>The township has 60 affordable housing units under the settlement agreement.
        Deadline: 2028.</p>
        </body></html>
        """
        with patch.object(self.scraper, "_fetch_page", return_value=html):
            results = self.scraper.scrape_municipality("Test Township", "https://testtown.gov")
        self.assertIn("commitments", results)
        self.assertIn("pages_found", results)
        self.assertGreaterEqual(len(results["commitments"]), 1)


class TestLoadStage1Results(unittest.TestCase):
    """Tests for load_stage1_results_to_db."""

    def setUp(self):
        """Create temp directory and database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        init_database(self.db_path)

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_stage1_results_valid_yaml(self):
        """Loads Stage 1 YAML results into database."""
        import yaml
        yaml_path = Path(self.temp_dir) / "stage1.yaml"
        data = {
            "municipalities": {
                "Newark": {"official_website": "https://newarknj.gov"},
                "Jersey City": {"official_website": "https://jerseycitynj.gov"},
            }
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        count = load_stage1_results_to_db(str(yaml_path), self.db_path)
        self.assertEqual(count, 2)
        munis = get_all_municipalities(self.db_path)
        self.assertEqual(len(munis), 2)

    def test_load_stage1_results_missing_municipalities_returns_zero(self):
        """Returns 0 when YAML has no municipalities key."""
        import yaml
        yaml_path = Path(self.temp_dir) / "bad.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump({"other_key": "value"}, f)
        count = load_stage1_results_to_db(str(yaml_path), self.db_path)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
