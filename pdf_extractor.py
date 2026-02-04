#!/usr/bin/env python3
"""
PDF Extractor for NJ Affordable Housing Tracker.

Extracts text and structured data from affordable housing PDFs including:
- Housing Element and Fair Share Plans
- Settlement Agreements
- COAH documents
- Planning board resolutions
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
import pdfplumber
import structlog

LOGGER = structlog.get_logger(__name__)


@dataclass
class ExtractedCommitment:
    """Structured data extracted from a PDF document."""
    municipality: Optional[str] = None
    document_type: Optional[str] = None
    total_units: Optional[int] = None
    low_income_units: Optional[int] = None
    moderate_income_units: Optional[int] = None
    very_low_income_units: Optional[int] = None
    senior_units: Optional[int] = None
    family_units: Optional[int] = None
    rental_units: Optional[int] = None
    for_sale_units: Optional[int] = None
    rehabilitation_units: Optional[int] = None
    deadline: Optional[str] = None
    settlement_date: Optional[str] = None
    developer: Optional[str] = None
    project_names: List[str] = field(default_factory=list)
    addresses: List[str] = field(default_factory=list)
    source_url: Optional[str] = None
    raw_text_snippet: Optional[str] = None
    confidence: float = 0.0


class PDFExtractor:
    """Extracts affordable housing data from PDF documents."""

    # Patterns for extracting unit counts
    UNIT_PATTERNS = [
        # Total obligation patterns
        (r'(?:total|overall)\s*(?:affordable\s*)?(?:housing\s*)?obligation[:\s]+(\d+)\s*units?', 'total_units'),
        (r'(\d+)\s*(?:total\s*)?(?:affordable\s*)?units?\s*(?:obligation|required|committed)', 'total_units'),
        (r'fair\s*share\s*(?:obligation|requirement)[:\s]+(\d+)', 'total_units'),
        (r'third\s*round\s*(?:obligation|requirement)[:\s]+(\d+)', 'total_units'),

        # Low income patterns
        (r'(\d+)\s*(?:very\s*)?low[- ]income\s*units?', 'low_income_units'),
        (r'low[- ]income[:\s]+(\d+)', 'low_income_units'),

        # Moderate income patterns
        (r'(\d+)\s*moderate[- ]income\s*units?', 'moderate_income_units'),
        (r'moderate[- ]income[:\s]+(\d+)', 'moderate_income_units'),

        # Very low income patterns
        (r'(\d+)\s*very\s*low[- ]income\s*units?', 'very_low_income_units'),
        (r'very\s*low[- ]income[:\s]+(\d+)', 'very_low_income_units'),

        # Senior patterns
        (r'(\d+)\s*(?:senior|age[- ]restricted|elderly)\s*units?', 'senior_units'),
        (r'(?:senior|age[- ]restricted|elderly)\s*(?:housing\s*)?[:\s]+(\d+)', 'senior_units'),

        # Family patterns
        (r'(\d+)\s*family\s*units?', 'family_units'),
        (r'family\s*(?:housing\s*)?[:\s]+(\d+)', 'family_units'),

        # Rental vs for-sale patterns
        (r'(\d+)\s*rental\s*units?', 'rental_units'),
        (r'rental[:\s]+(\d+)', 'rental_units'),
        (r'(\d+)\s*(?:for[- ]sale|ownership)\s*units?', 'for_sale_units'),

        # Rehabilitation patterns
        (r'(\d+)\s*(?:rehabilitation|rehab)\s*units?', 'rehabilitation_units'),
        (r'(?:rehabilitation|rehab)[:\s]+(\d+)', 'rehabilitation_units'),
    ]

    # Patterns for document type detection
    DOCUMENT_TYPE_PATTERNS = [
        (r'housing\s*element\s*(?:and|&)?\s*fair\s*share\s*plan', 'Housing Element and Fair Share Plan'),
        (r'settlement\s*agreement', 'Settlement Agreement'),
        (r'consent\s*(?:order|judgment|decree)', 'Consent Order'),
        (r'compliance\s*report', 'Compliance Report'),
        (r'spending\s*plan', 'Spending Plan'),
        (r'resolution\s*of\s*(?:participation|intent)', 'Resolution of Participation'),
        (r'redevelopment\s*plan', 'Redevelopment Plan'),
        (r'affordable\s*housing\s*plan', 'Affordable Housing Plan'),
        (r'inclusionary\s*(?:zoning|development)\s*(?:ordinance|plan)', 'Inclusionary Development Plan'),
    ]

    # Deadline/year patterns
    DEADLINE_PATTERNS = [
        r'(?:deadline|due\s*date|completion\s*date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'(?:by|before|no\s*later\s*than)\s+(?:december\s+31,?\s+)?(20\d{2})',
        r'through\s+(?:december\s+31,?\s+)?(20\d{2})',
        r'(20\d{2})\s*(?:deadline|goal|target)',
        r'third\s*round[:\s]+.*?(20\d{2})',
    ]

    # Project name patterns (look for capitalized development names)
    PROJECT_PATTERNS = [
        r'(?:the\s+)?([A-Z][A-Za-z\s]+(?:Village|Gardens|Apartments|Commons|Place|Court|Homes|Manor|Towers|Heights|Park|Estate|Ridge|View|Point|Landing|Square|Terrace|Green|Brook|Glen|Run|Way|Circle|Lane))',
        r'(?:known\s+as|called)\s+["\']?([A-Z][A-Za-z\s]+)["\']?',
    ]

    # Address patterns
    ADDRESS_PATTERNS = [
        r'(\d+\s+[A-Z][A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl)\.?)',
        r'(?:block|lot)\s+(\d+(?:\.\d+)?)',
    ]

    def __init__(self, temp_dir: Path = None):
        self.temp_dir = temp_dir or Path(tempfile.gettempdir())
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def download_pdf(self, url: str) -> Optional[Path]:
        """Download a PDF from URL to temp directory."""
        try:
            LOGGER.info("Downloading PDF", url=url)
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower() and not url.lower().endswith('.pdf'):
                LOGGER.warning("URL may not be a PDF", url=url, content_type=content_type)

            # Generate temp filename
            parsed = urlparse(url)
            filename = Path(parsed.path).name or 'document.pdf'
            if not filename.endswith('.pdf'):
                filename += '.pdf'

            temp_path = self.temp_dir / filename

            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            LOGGER.info("PDF downloaded", path=str(temp_path), size=temp_path.stat().st_size)
            return temp_path

        except Exception as e:
            LOGGER.error("Failed to download PDF", url=url, error=str(e))
            return None

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract all text from a PDF file."""
        try:
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                LOGGER.info("Extracting text from PDF", pages=len(pdf.pages))
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

            full_text = '\n\n'.join(text_parts)
            LOGGER.info("Text extracted", characters=len(full_text))
            return full_text

        except Exception as e:
            LOGGER.error("Failed to extract text from PDF", path=str(pdf_path), error=str(e))
            return ""

    def extract_tables_from_pdf(self, pdf_path: Path) -> List[List[List[str]]]:
        """Extract tables from a PDF file."""
        tables = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_tables = page.extract_tables()
                    if page_tables:
                        LOGGER.debug("Found tables on page", page=page_num + 1, count=len(page_tables))
                        tables.extend(page_tables)

            LOGGER.info("Tables extracted", total_tables=len(tables))
            return tables

        except Exception as e:
            LOGGER.error("Failed to extract tables from PDF", path=str(pdf_path), error=str(e))
            return []

    def extract_commitment_data(self, text: str, source_url: str = None,
                                municipality: str = None) -> ExtractedCommitment:
        """Extract structured commitment data from PDF text."""
        commitment = ExtractedCommitment(
            municipality=municipality,
            source_url=source_url,
        )

        text_lower = text.lower()

        # Detect document type
        for pattern, doc_type in self.DOCUMENT_TYPE_PATTERNS:
            if re.search(pattern, text_lower):
                commitment.document_type = doc_type
                break

        # Extract unit counts
        for pattern, field_name in self.UNIT_PATTERNS:
            matches = re.findall(pattern, text_lower)
            if matches:
                try:
                    # Take the largest number found for this field
                    value = max(int(m) for m in matches if m.isdigit())
                    if 0 < value < 10000:  # Sanity check
                        current = getattr(commitment, field_name)
                        if current is None or value > current:
                            setattr(commitment, field_name, value)
                except (ValueError, TypeError):
                    pass

        # Extract deadline
        for pattern in self.DEADLINE_PATTERNS:
            matches = re.findall(pattern, text_lower)
            if matches:
                commitment.deadline = matches[0]
                break

        # Extract project names (from original case text)
        for pattern in self.PROJECT_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                name = match.strip()
                if len(name) > 5 and name not in commitment.project_names:
                    commitment.project_names.append(name)

        # Extract addresses
        for pattern in self.ADDRESS_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                addr = match.strip()
                if addr not in commitment.addresses:
                    commitment.addresses.append(addr)

        # Calculate confidence score
        confidence = 0.0
        if commitment.total_units:
            confidence += 0.3
        if commitment.document_type:
            confidence += 0.2
        if commitment.deadline:
            confidence += 0.1
        if commitment.project_names:
            confidence += 0.1
        if commitment.low_income_units or commitment.moderate_income_units:
            confidence += 0.2
        if commitment.addresses:
            confidence += 0.1
        commitment.confidence = min(confidence, 1.0)

        # Store text snippet for context
        # Find a relevant section of text
        for keyword in ['obligation', 'settlement', 'units', 'affordable']:
            idx = text_lower.find(keyword)
            if idx != -1:
                start = max(0, idx - 200)
                end = min(len(text), idx + 500)
                commitment.raw_text_snippet = text[start:end].strip()
                break

        LOGGER.info(
            "Extracted commitment data",
            total_units=commitment.total_units,
            document_type=commitment.document_type,
            confidence=commitment.confidence,
            projects=len(commitment.project_names),
        )

        return commitment

    def process_pdf_url(self, url: str, municipality: str = None) -> Optional[ExtractedCommitment]:
        """Download and process a PDF from URL."""
        # Download PDF
        pdf_path = self.download_pdf(url)
        if not pdf_path:
            return None

        try:
            # Extract text
            text = self.extract_text_from_pdf(pdf_path)
            if not text:
                return None

            # Extract structured data
            commitment = self.extract_commitment_data(text, url, municipality)

            # Also try to extract from tables
            tables = self.extract_tables_from_pdf(pdf_path)
            if tables:
                self._enhance_from_tables(commitment, tables)

            return commitment

        finally:
            # Clean up temp file
            try:
                pdf_path.unlink()
            except Exception:
                pass

    def _enhance_from_tables(self, commitment: ExtractedCommitment,
                            tables: List[List[List[str]]]) -> None:
        """Try to extract additional data from PDF tables."""
        for table in tables:
            if not table:
                continue

            # Look for unit count tables
            for row in table:
                if not row:
                    continue

                row_text = ' '.join(str(cell) for cell in row if cell).lower()

                # Check if row contains unit information
                if any(kw in row_text for kw in ['units', 'obligation', 'total']):
                    # Try to find numbers in the row
                    for cell in row:
                        if cell and str(cell).isdigit():
                            value = int(cell)
                            if 0 < value < 10000:
                                # Try to determine what type of units
                                if 'low' in row_text and 'very' not in row_text:
                                    if not commitment.low_income_units:
                                        commitment.low_income_units = value
                                elif 'moderate' in row_text:
                                    if not commitment.moderate_income_units:
                                        commitment.moderate_income_units = value
                                elif 'total' in row_text:
                                    if not commitment.total_units or value > commitment.total_units:
                                        commitment.total_units = value


def main():
    """Test the PDF extractor."""
    from log_config import configure_logging
    configure_logging()

    import argparse
    parser = argparse.ArgumentParser(description="PDF Extractor for Affordable Housing Documents")
    parser.add_argument("--url", type=str, help="URL of PDF to extract")
    parser.add_argument("--file", type=str, help="Local PDF file to extract")
    parser.add_argument("--municipality", type=str, help="Municipality name")

    args = parser.parse_args()

    extractor = PDFExtractor()

    if args.url:
        commitment = extractor.process_pdf_url(args.url, args.municipality)
        if commitment:
            LOGGER.info("Extraction complete", **vars(commitment))
    elif args.file:
        text = extractor.extract_text_from_pdf(Path(args.file))
        commitment = extractor.extract_commitment_data(text, args.file, args.municipality)
        LOGGER.info("Extraction complete", **vars(commitment))
    else:
        LOGGER.error("Please provide --url or --file")


if __name__ == "__main__":
    main()
