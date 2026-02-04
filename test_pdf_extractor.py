#!/usr/bin/env python3
"""
Tests for PDFExtractor module.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from pdf_extractor import PDFExtractor, ExtractedCommitment


class TestExtractedCommitment(unittest.TestCase):
    """Tests for ExtractedCommitment dataclass."""

    def test_default_values(self):
        """Test that ExtractedCommitment has correct default values."""
        commitment = ExtractedCommitment()

        self.assertIsNone(commitment.municipality)
        self.assertIsNone(commitment.document_type)
        self.assertIsNone(commitment.total_units)
        self.assertIsNone(commitment.low_income_units)
        self.assertIsNone(commitment.moderate_income_units)
        self.assertIsNone(commitment.very_low_income_units)
        self.assertIsNone(commitment.senior_units)
        self.assertIsNone(commitment.family_units)
        self.assertIsNone(commitment.rental_units)
        self.assertIsNone(commitment.for_sale_units)
        self.assertIsNone(commitment.rehabilitation_units)
        self.assertIsNone(commitment.deadline)
        self.assertIsNone(commitment.settlement_date)
        self.assertIsNone(commitment.developer)
        self.assertEqual(commitment.project_names, [])
        self.assertEqual(commitment.addresses, [])
        self.assertIsNone(commitment.source_url)
        self.assertIsNone(commitment.raw_text_snippet)
        self.assertEqual(commitment.confidence, 0.0)

    def test_with_values(self):
        """Test ExtractedCommitment with provided values."""
        commitment = ExtractedCommitment(
            municipality="Newark",
            document_type="Settlement Agreement",
            total_units=500,
            low_income_units=250,
            moderate_income_units=250,
            confidence=0.8
        )

        self.assertEqual(commitment.municipality, "Newark")
        self.assertEqual(commitment.document_type, "Settlement Agreement")
        self.assertEqual(commitment.total_units, 500)
        self.assertEqual(commitment.low_income_units, 250)
        self.assertEqual(commitment.moderate_income_units, 250)
        self.assertEqual(commitment.confidence, 0.8)


class TestPDFExtractor(unittest.TestCase):
    """Tests for PDFExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = PDFExtractor()

    def test_init_default_temp_dir(self):
        """Test PDFExtractor initializes with default temp directory."""
        extractor = PDFExtractor()
        self.assertIsNotNone(extractor.temp_dir)
        self.assertIsNotNone(extractor.session)

    def test_init_custom_temp_dir(self):
        """Test PDFExtractor initializes with custom temp directory."""
        custom_dir = Path(tempfile.gettempdir()) / "custom_test"
        extractor = PDFExtractor(temp_dir=custom_dir)
        self.assertEqual(extractor.temp_dir, custom_dir)

    def test_extract_commitment_data_document_type_detection(self):
        """Test document type detection from text."""
        test_cases = [
            ("This is a housing element and fair share plan document", "Housing Element and Fair Share Plan"),
            ("Settlement agreement between parties", "Settlement Agreement"),
            ("Consent order issued by court", "Consent Order"),
            ("Annual compliance report for municipality", "Compliance Report"),
            ("Spending plan for affordable housing trust", "Spending Plan"),
            ("Resolution of participation filed", "Resolution of Participation"),
            ("Redevelopment plan for downtown area", "Redevelopment Plan"),
            ("Affordable housing plan submitted", "Affordable Housing Plan"),
            ("Inclusionary zoning ordinance adopted", "Inclusionary Development Plan"),
        ]

        for text, expected_type in test_cases:
            with self.subTest(text=text[:50]):
                commitment = self.extractor.extract_commitment_data(text)
                self.assertEqual(commitment.document_type, expected_type)

    def test_extract_commitment_data_total_units(self):
        """Test total units extraction from text."""
        test_cases = [
            ("Total affordable housing obligation: 500 units", 500),
            ("The 250 total affordable units required", 250),
            ("Fair share obligation: 1000", 1000),
            ("Third round requirement: 750", 750),
        ]

        for text, expected_units in test_cases:
            with self.subTest(text=text):
                commitment = self.extractor.extract_commitment_data(text)
                self.assertEqual(commitment.total_units, expected_units)

    def test_extract_commitment_data_income_units(self):
        """Test income-based unit extraction."""
        text = """
        The municipality shall provide:
        - 100 low-income units
        - 150 moderate-income units
        - 50 very low-income units
        """
        commitment = self.extractor.extract_commitment_data(text)

        self.assertEqual(commitment.low_income_units, 100)
        self.assertEqual(commitment.moderate_income_units, 150)
        self.assertEqual(commitment.very_low_income_units, 50)

    def test_extract_commitment_data_senior_units(self):
        """Test senior/age-restricted unit extraction."""
        test_cases = [
            ("75 senior units planned", 75),
            ("age-restricted housing: 100", 100),
            ("50 elderly units provided", 50),
        ]

        for text, expected_units in test_cases:
            with self.subTest(text=text):
                commitment = self.extractor.extract_commitment_data(text)
                self.assertEqual(commitment.senior_units, expected_units)

    def test_extract_commitment_data_rental_units(self):
        """Test rental vs for-sale unit extraction."""
        text = "Project includes 200 rental units and 100 for-sale units"
        commitment = self.extractor.extract_commitment_data(text)

        self.assertEqual(commitment.rental_units, 200)
        self.assertEqual(commitment.for_sale_units, 100)

    def test_extract_commitment_data_deadline(self):
        """Test deadline extraction."""
        test_cases = [
            ("deadline: 12/31/2025", "12/31/2025"),
            ("by December 31, 2030", "2030"),
            ("through 2028", "2028"),
            ("2027 deadline for completion", "2027"),
        ]

        for text, expected_deadline in test_cases:
            with self.subTest(text=text):
                commitment = self.extractor.extract_commitment_data(text)
                self.assertEqual(commitment.deadline, expected_deadline)

    def test_extract_commitment_data_project_names(self):
        """Test project name extraction."""
        text = """
        The Riverside Gardens development will provide 50 units.
        Oakwood Commons will have 30 units.
        The project known as "Harbor View Apartments" includes 100 units.
        """
        commitment = self.extractor.extract_commitment_data(text)

        self.assertIn("Riverside Gardens", commitment.project_names)
        self.assertIn("Oakwood Commons", commitment.project_names)

    def test_extract_commitment_data_addresses(self):
        """Test address extraction."""
        text = """
        Located at 123 Main Street and 456 Oak Avenue.
        Block 101 and Lot 5.02 are included.
        """
        commitment = self.extractor.extract_commitment_data(text)

        self.assertTrue(len(commitment.addresses) > 0)
        # Check for street address pattern
        address_text = ' '.join(commitment.addresses).lower()
        self.assertTrue('123' in address_text or 'main' in address_text)

    def test_extract_commitment_data_confidence_scoring(self):
        """Test confidence score calculation."""
        # High confidence: has multiple data points
        high_conf_text = """
        Housing Element and Fair Share Plan
        Total obligation: 500 units
        100 low-income units
        Deadline: 2025
        Located at 123 Main Street
        The Riverside Village project
        """
        high_commitment = self.extractor.extract_commitment_data(high_conf_text)
        self.assertGreater(high_commitment.confidence, 0.5)

        # Low confidence: minimal data
        low_conf_text = "Some general text about housing"
        low_commitment = self.extractor.extract_commitment_data(low_conf_text)
        self.assertLess(low_commitment.confidence, 0.3)

    def test_extract_commitment_data_preserves_municipality(self):
        """Test that municipality is preserved from input."""
        text = "Total units: 100"
        commitment = self.extractor.extract_commitment_data(
            text, source_url="http://example.com", municipality="Test Township"
        )

        self.assertEqual(commitment.municipality, "Test Township")
        self.assertEqual(commitment.source_url, "http://example.com")

    def test_extract_commitment_data_raw_text_snippet(self):
        """Test raw text snippet extraction."""
        text = "Some text " * 100 + "affordable housing obligation of 500 units" + " more text" * 100
        commitment = self.extractor.extract_commitment_data(text)

        self.assertIsNotNone(commitment.raw_text_snippet)
        self.assertIn("affordable", commitment.raw_text_snippet.lower())

    def test_extract_commitment_data_sanity_checks(self):
        """Test that unreasonable values are rejected."""
        # Units too large (> 10000)
        text = "Total units: 50000"
        commitment = self.extractor.extract_commitment_data(text)
        self.assertIsNone(commitment.total_units)

        # Units zero or negative (handled by regex)
        text2 = "Total units: 0"
        commitment2 = self.extractor.extract_commitment_data(text2)
        self.assertIsNone(commitment2.total_units)

    @patch('pdf_extractor.pdfplumber')
    def test_extract_text_from_pdf_success(self, mock_pdfplumber):
        """Test successful text extraction from PDF."""
        # Mock pdfplumber
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 text"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page 2 text"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber.open.return_value = mock_pdf

        result = self.extractor.extract_text_from_pdf(Path("/fake/path.pdf"))

        self.assertEqual(result, "Page 1 text\n\nPage 2 text")

    @patch('pdf_extractor.pdfplumber')
    def test_extract_text_from_pdf_error(self, mock_pdfplumber):
        """Test error handling in PDF text extraction."""
        mock_pdfplumber.open.side_effect = Exception("PDF error")

        result = self.extractor.extract_text_from_pdf(Path("/fake/path.pdf"))

        self.assertEqual(result, "")

    @patch('pdf_extractor.pdfplumber')
    def test_extract_tables_from_pdf(self, mock_pdfplumber):
        """Test table extraction from PDF."""
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["Header1", "Header2"], ["Row1Col1", "Row1Col2"]]
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber.open.return_value = mock_pdf

        result = self.extractor.extract_tables_from_pdf(Path("/fake/path.pdf"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], ["Header1", "Header2"])

    def test_enhance_from_tables_unit_extraction(self):
        """Test unit extraction from tables."""
        commitment = ExtractedCommitment()
        tables = [
            [
                ["Type", "Units"],
                ["Low Income", "50"],
                ["Moderate Income", "100"],
                ["Total", "150"]
            ]
        ]

        self.extractor._enhance_from_tables(commitment, tables)

        # Should extract total from table
        self.assertEqual(commitment.total_units, 150)

    @patch.object(PDFExtractor, 'session')
    def test_download_pdf_success(self, mock_session):
        """Test successful PDF download."""
        mock_response = MagicMock()
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_response.iter_content.return_value = [b'PDF content']
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = PDFExtractor(temp_dir=Path(tmpdir))
            extractor.session = mock_session

            result = extractor.download_pdf("http://example.com/test.pdf")

            self.assertIsNotNone(result)
            self.assertTrue(str(result).endswith('.pdf'))

    @patch.object(PDFExtractor, 'session')
    def test_download_pdf_failure(self, mock_session):
        """Test PDF download failure handling."""
        mock_session.get.side_effect = Exception("Network error")

        extractor = PDFExtractor()
        extractor.session = mock_session

        result = extractor.download_pdf("http://example.com/test.pdf")

        self.assertIsNone(result)


class TestPDFExtractorPatterns(unittest.TestCase):
    """Tests for pattern matching in PDFExtractor."""

    def test_unit_patterns_comprehensive(self):
        """Test all unit patterns match correctly."""
        extractor = PDFExtractor()

        # Test each pattern type
        patterns_tests = [
            # Total obligation patterns
            ("total affordable housing obligation: 500 units", "total_units", 500),
            ("overall housing obligation: 300 units", "total_units", 300),
            ("500 total units obligation", "total_units", 500),
            ("fair share obligation: 750", "total_units", 750),
            ("third round obligation: 600", "total_units", 600),

            # Rehabilitation patterns
            ("100 rehabilitation units", "rehabilitation_units", 100),
            ("rehab: 75", "rehabilitation_units", 75),
        ]

        for text, field, expected in patterns_tests:
            with self.subTest(text=text):
                commitment = extractor.extract_commitment_data(text)
                actual = getattr(commitment, field)
                self.assertEqual(actual, expected, f"Failed for '{text}': expected {expected}, got {actual}")


if __name__ == '__main__':
    unittest.main()
