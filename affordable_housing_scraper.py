#!/usr/bin/env python3
"""
Stage 2: Affordable Housing Commitment Scraper

This script scrapes municipal websites to find affordable housing commitments,
settlement agreements, and housing plans.
"""

import re
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import structlog

from database import (
    get_connection, init_database, get_all_municipalities,
    insert_municipality, get_municipality, update_municipality_website,
    insert_commitment_if_new, record_scraped_page, is_page_scraped,
    bulk_insert_municipalities, DEFAULT_DB_PATH
)

LOGGER = structlog.get_logger(__name__)

# Keywords that indicate affordable housing content
AFFORDABLE_HOUSING_KEYWORDS = [
    'affordable housing',
    'fair share',
    'coah',
    'council on affordable housing',
    'low income housing',
    'moderate income housing',
    'inclusionary zoning',
    'housing element',
    'housing plan',
    'mount laurel',
    'settlement agreement',
    'builders remedy',
    'housing obligation',
    'affordable units',
    'deed restricted',
    'affordable rental',
    'senior housing',
    'age restricted housing',
    'workforce housing',
]

# Keywords for finding planning/zoning pages
PLANNING_KEYWORDS = [
    'planning board',
    'planning department',
    'zoning board',
    'land use',
    'master plan',
    'housing element',
    'redevelopment',
    'affordable housing',
]

# File extensions to look for (PDFs often contain the detailed plans)
DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx']

# Priority-ordered unit extraction patterns (higher confidence first)
# Each tuple: (pattern, confidence_boost)
UNIT_PATTERNS_PRIORITY = [
    # Highest confidence: explicit obligation statements
    (r'(?:total\s+)?(?:affordable\s+)?(?:housing\s+)?obligation\s*(?:of\s*|:\s*)?(\d+)\s*units?', 1.0),
    (r'committed\s+to\s+(?:provide\s+)?(\d+)\s*(?:affordable\s+)?units?', 0.9),
    (r'shall\s+(?:provide|construct|build)\s+(\d+)\s*(?:affordable\s+)?units?', 0.9),
    (r'required\s+to\s+(?:provide|build)\s+(\d+)\s*(?:affordable\s+)?units?', 0.9),
    # Medium confidence: general mentions with clear context
    (r'(\d+)\s+(?:affordable|deed[- ]restricted|low[- ]income|moderate[- ]income)\s+(?:housing\s+)?units?', 0.7),
    (r'(?:affordable|low[- ]income|moderate[- ]income)\s+(?:housing\s+)?units?[:\s]+(\d+)', 0.7),
    # Lower confidence: ambiguous patterns
    (r'(\d+)\s+units?\s+(?:of\s+)?affordable\s+housing', 0.5),
    (r'total\s*(?:of\s*)?(\d+)\s*(?:affordable\s*)?units?', 0.5),
]

# Patterns that indicate tentative/uncertain language (reject matches in these contexts)
EXCLUSION_PATTERNS = [
    r'up\s+to\s+(\d+)',
    r'(?:may|might|could)\s+(?:include|provide|require).*?(\d+)',
    r'(?:fewer|less)\s+than\s+(\d+)',
    r'(?:originally|previously|formerly)\s+.*?(\d+)',
    r'(?:proposed|potential|possible)\s+(\d+)',
    r'(?:maximum|minimum)\s+(?:of\s+)?(\d+)',
]

# Patterns that indicate NO obligation or rejection (skip these pages)
NEGATIVE_PATTERNS = [
    r'(?:does\s+not|doesn\'t|do\s+not)\s+have\s+(?:an?\s+)?(?:affordable\s+)?(?:housing\s+)?obligation',
    r'(?:no|zero)\s+(?:affordable\s+)?(?:housing\s+)?(?:obligation|requirement)',
    r'(?:exempt|exempted)\s+from\s+(?:affordable\s+)?housing',
    r'(?:rejected|denied|withdrawn)\s+(?:the\s+)?(?:affordable\s+)?(?:housing\s+)?(?:plan|proposal)',
    r'not\s+(?:subject|required)\s+to\s+(?:provide\s+)?(?:affordable\s+)?housing',
]

# Words that indicate a phrase is NOT a project name
PROJECT_EXCLUSION_WORDS = [
    'Committee', 'Council', 'Board', 'Authority', 'Association',
    'Commission', 'Department', 'Office', 'Agency', 'Organization',
    'Foundation', 'Institute', 'Coalition', 'Alliance', 'Group',
]


@dataclass
class AffordableHousingCommitment:
    """Represents an extracted affordable housing commitment."""
    municipality: str
    commitment_type: Optional[str] = None
    total_units: Optional[int] = None
    low_income_units: Optional[int] = None
    moderate_income_units: Optional[int] = None
    deadline: Optional[str] = None
    developer: Optional[str] = None
    project_name: Optional[str] = None
    location_address: Optional[str] = None
    source_url: Optional[str] = None
    source_document_type: Optional[str] = None
    date_announced: Optional[str] = None
    raw_text: Optional[str] = None
    confidence: float = 0.0

    def calculate_confidence(self) -> float:
        """Calculate confidence score based on extracted data quality."""
        score = 0.0
        if self.total_units and self.total_units > 0:
            score += 0.3
        if self.commitment_type:
            score += 0.2
        if self.deadline:
            score += 0.1
        if self.project_name:
            score += 0.1
        if self.low_income_units or self.moderate_income_units:
            score += 0.2
        if self.location_address:
            score += 0.1
        return min(score, 1.0)


class AffordableHousingScraper:
    """Scrapes municipal websites for affordable housing information."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.delay_between_requests = 1.5  # seconds

    def scrape_municipality(self, name: str, website: str) -> Dict[str, Any]:
        """
        Scrape a municipality's website for affordable housing information.
        Returns a dict with findings and any extracted commitments.
        """
        LOGGER.info(f"Scraping {name}: {website}")
        results = {
            'municipality': name,
            'website': website,
            'pages_found': [],
            'documents_found': [],
            'commitments': [],
            'errors': [],
        }

        try:
            # Step 1: Get the homepage and look for relevant links
            homepage_content = self._fetch_page(website)
            if not homepage_content:
                results['errors'].append(f"Could not fetch homepage: {website}")
                return results

            soup = BeautifulSoup(homepage_content, 'html.parser')

            # Step 2: Find links to planning/housing pages
            relevant_links = self._find_relevant_links(soup, website)
            results['pages_found'] = relevant_links

            # Step 3: Search homepage for affordable housing content
            homepage_findings = self._extract_housing_info(homepage_content, website, name)
            if homepage_findings:
                results['commitments'].extend(homepage_findings)

            # Step 4: Scrape each relevant page
            for link in relevant_links[:10]:  # Limit to avoid overloading
                time.sleep(self.delay_between_requests)

                if is_page_scraped(link['url'], self.db_path):
                    LOGGER.debug(f"Skipping already scraped: {link['url']}")
                    continue

                page_content = self._fetch_page(link['url'])
                if page_content:
                    # Check for document links
                    page_soup = BeautifulSoup(page_content, 'html.parser')
                    doc_links = self._find_document_links(page_soup, link['url'])
                    results['documents_found'].extend(doc_links)

                    # Extract housing info from page
                    page_findings = self._extract_housing_info(page_content, link['url'], name)
                    if page_findings:
                        results['commitments'].extend(page_findings)

                    record_scraped_page(link['url'], page_type=link.get('type'), db_path=self.db_path)

            LOGGER.info(f"Completed {name}: found {len(results['commitments'])} potential commitments, "
                       f"{len(results['documents_found'])} documents")

        except Exception as e:
            LOGGER.error(f"Error scraping {name}: {e}")
            results['errors'].append(str(e))

        return results

    def _fetch_page(self, url: str, timeout: int = 15) -> Optional[str]:
        """Fetch a page and return its HTML content."""
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            LOGGER.warning(f"Failed to fetch {url}: {e}")
            return None

    def _find_relevant_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Find links that might lead to affordable housing information."""
        relevant_links = []
        seen_urls = set()

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()

            # Skip empty or javascript links
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue

            # Make absolute URL
            full_url = urljoin(base_url, href)

            # Only follow links on same domain
            if urlparse(full_url).netloc != urlparse(base_url).netloc:
                continue

            # Skip if already seen
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Check if link text matches planning/housing keywords
            link_type = None
            for keyword in PLANNING_KEYWORDS:
                if keyword in text:
                    link_type = keyword
                    break

            # Also check href for keywords
            if not link_type:
                href_lower = href.lower()
                for keyword in PLANNING_KEYWORDS:
                    if keyword.replace(' ', '') in href_lower or keyword.replace(' ', '-') in href_lower:
                        link_type = keyword
                        break

            if link_type:
                relevant_links.append({
                    'url': full_url,
                    'text': link.get_text(strip=True),
                    'type': link_type,
                })

        LOGGER.debug(f"Found {len(relevant_links)} relevant links")
        return relevant_links

    def _find_document_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Find links to PDF and other documents."""
        documents = []

        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text(strip=True)

            # Check if it's a document
            is_document = any(ext in href for ext in DOCUMENT_EXTENSIONS)

            # Check if it's affordable housing related
            is_relevant = any(kw in text.lower() or kw in href for kw in AFFORDABLE_HOUSING_KEYWORDS)

            if is_document and is_relevant:
                full_url = urljoin(base_url, link.get('href', ''))
                documents.append({
                    'url': full_url,
                    'text': text,
                    'type': 'document',
                })

        return documents

    def _extract_housing_info(self, html_content: str, source_url: str,
                             municipality: str) -> List[AffordableHousingCommitment]:
        """Extract affordable housing information from page content."""
        commitments = []

        # Convert to lowercase for searching
        text = BeautifulSoup(html_content, 'html.parser').get_text()
        text_lower = text.lower()

        # Check if page has any affordable housing keywords
        has_keywords = any(kw in text_lower for kw in AFFORDABLE_HOUSING_KEYWORDS)
        if not has_keywords:
            return []

        LOGGER.debug(f"Page {source_url} contains affordable housing keywords")

        # Check for negative indicators (no obligation, rejection, etc.)
        if self._has_negative_indicators(text_lower):
            LOGGER.debug(f"Page {source_url} contains negative indicators, skipping extraction")
            return []

        # Try to extract structured information
        commitment = AffordableHousingCommitment(
            municipality=municipality,
            source_url=source_url,
        )

        # Extract unit counts using priority-ordered patterns
        commitment.total_units = self._extract_unit_count(text_lower)

        # Extract commitment types
        if 'settlement agreement' in text_lower:
            commitment.commitment_type = 'Settlement Agreement'
        elif 'coah' in text_lower or 'council on affordable housing' in text_lower:
            commitment.commitment_type = 'COAH'
        elif 'builders remedy' in text_lower or "builder's remedy" in text_lower:
            commitment.commitment_type = 'Builders Remedy'
        elif 'mount laurel' in text_lower:
            commitment.commitment_type = 'Mount Laurel'
        elif 'inclusionary' in text_lower:
            commitment.commitment_type = 'Inclusionary Zoning'

        # Extract deadline with validation (only future years)
        commitment.deadline = self._extract_deadline(text_lower)

        # Extract project names with stricter validation
        commitment.project_name = self._extract_project_name(text)

        # Store relevant text snippet
        for kw in AFFORDABLE_HOUSING_KEYWORDS:
            idx = text_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 200)
                end = min(len(text), idx + 500)
                commitment.raw_text = text[start:end].strip()
                break

        # Calculate confidence score
        commitment.confidence = commitment.calculate_confidence()

        # Only add if we found something meaningful with sufficient confidence
        if commitment.total_units or commitment.commitment_type or commitment.project_name:
            commitments.append(commitment)
            LOGGER.info(f"Extracted commitment: {commitment.commitment_type}, "
                       f"{commitment.total_units} units, project: {commitment.project_name}, "
                       f"confidence: {commitment.confidence:.2f}")

        return commitments

    def _has_negative_indicators(self, text_lower: str) -> bool:
        """Check if text contains negative indicators (no obligation, rejection, etc.)."""
        for pattern in NEGATIVE_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    def _extract_unit_count(self, text_lower: str) -> Optional[int]:
        """
        Extract unit count using priority-ordered patterns.
        Returns the first valid match from highest-confidence patterns.
        """
        # First, find numbers that appear in exclusion contexts (tentative language)
        excluded_numbers = set()
        for pattern in EXCLUSION_PATTERNS:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                try:
                    excluded_numbers.add(int(match))
                except (ValueError, TypeError):
                    pass

        # Try patterns in priority order
        for pattern, confidence in UNIT_PATTERNS_PRIORITY:
            matches = re.findall(pattern, text_lower)
            if matches:
                # Filter out excluded numbers and invalid values
                valid_units = []
                for match in matches:
                    try:
                        units = int(match)
                        if units > 0 and units < 10000 and units not in excluded_numbers:
                            valid_units.append(units)
                    except (ValueError, TypeError):
                        pass

                if valid_units:
                    # For high-confidence patterns, take first match
                    # For low-confidence patterns, take max to get total
                    if confidence >= 0.9:
                        return valid_units[0]
                    else:
                        return max(valid_units)

        return None

    def _extract_deadline(self, text_lower: str) -> Optional[str]:
        """
        Extract deadline year, filtering out historical dates.
        Only returns years in the future or very recent past.
        """
        current_year = datetime.now().year
        min_valid_year = current_year - 1  # Allow last year (plans in progress)
        max_valid_year = current_year + 15  # Reasonable planning horizon

        year_patterns = [
            r'(?:deadline|due\s+date)(?:\s+is)?[:\s]+(20\d{2})',
            r'(?:by|through|before)\s+(20\d{2})',
            r'(20\d{2})\s*(?:deadline|goal|target)',
            r'(?:complete|completed)\s+by\s+(20\d{2})',
            r'new\s+deadline[:\s]+(?:is\s+)?(20\d{2})',
        ]

        valid_years = []
        for pattern in year_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                try:
                    year = int(match)
                    if min_valid_year <= year <= max_valid_year:
                        valid_years.append(str(year))
                except (ValueError, TypeError):
                    pass

        # Return the latest valid year (most likely the current deadline)
        if valid_years:
            return max(valid_years)
        return None

    def _extract_project_name(self, text: str) -> Optional[str]:
        """
        Extract project name with stricter validation.
        Excludes committee names, organization names, etc.
        """
        # Pattern for development names with common suffixes
        project_pattern = (
            r'(?:the\s+)?([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]+){0,3}\s+'
            r'(?:Village|Gardens|Apartments|Commons|Place|Court|Homes|Manor|'
            r'Towers|Heights|Park|Estate|Ridge|View|Point|Landing|Square|'
            r'Terrace|Green|Brook|Glen|Run|Way|Circle|Lane))'
        )

        matches = re.findall(project_pattern, text)

        for match in matches:
            name = match.strip()

            # Skip if name contains exclusion words
            if any(word in name for word in PROJECT_EXCLUSION_WORDS):
                continue

            # Skip if too short (likely partial match)
            if len(name) < 8:
                continue

            # Skip if too many words (likely captured too much)
            word_count = len(name.split())
            if word_count > 5:
                continue

            return name

        return None

    def scrape_all_municipalities(self, limit: int = None) -> List[Dict[str, Any]]:
        """Scrape all municipalities in the database."""
        municipalities = get_all_municipalities(self.db_path)

        if limit:
            municipalities = municipalities[:limit]

        all_results = []
        for muni in municipalities:
            if not muni.get('official_website'):
                LOGGER.warning(f"No website for {muni['name']}, skipping")
                continue

            results = self.scrape_municipality(muni['name'], muni['official_website'])
            all_results.append(results)

            # Save commitments to database (skips duplicates by source URL)
            for commitment in results.get('commitments', []):
                insert_commitment_if_new(
                    municipality_id=muni['id'],
                    commitment_type=commitment.commitment_type,
                    total_units=commitment.total_units,
                    low_income_units=commitment.low_income_units,
                    moderate_income_units=commitment.moderate_income_units,
                    deadline=commitment.deadline,
                    developer=commitment.developer,
                    project_name=commitment.project_name,
                    location_address=commitment.location_address,
                    source_document_url=commitment.source_url,
                    source_document_type=commitment.source_document_type,
                    notes=commitment.raw_text[:500] if commitment.raw_text else None,
                    db_path=self.db_path,
                )

            time.sleep(self.delay_between_requests)

        return all_results


def load_stage1_results_to_db(yaml_path: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Load Stage 1 results (municipality websites) into the database."""
    import yaml

    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not data or 'municipalities' not in data:
        LOGGER.error("Invalid YAML format")
        return 0

    municipalities = []
    for name, info in data['municipalities'].items():
        municipalities.append({
            'name': name,
            'official_website': info.get('official_website'),
        })

    count = bulk_insert_municipalities(municipalities, db_path)
    LOGGER.info(f"Loaded {count} municipalities from Stage 1 results")
    return count


def main():
    """Main function for Stage 2 scraper."""
    from log_config import configure_logging
    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Stage 2: Affordable Housing Scraper")
    parser.add_argument("--load-stage1", type=str, help="Load Stage 1 YAML results into database")
    parser.add_argument("--scrape", type=str, help="Scrape a specific municipality by name")
    parser.add_argument("--scrape-all", action="store_true", help="Scrape all municipalities")
    parser.add_argument("--limit", type=int, help="Limit number of municipalities to scrape")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Database path")

    args = parser.parse_args()
    db_path = Path(args.db)

    # Ensure database exists
    init_database(db_path)

    scraper = AffordableHousingScraper(db_path)

    if args.load_stage1:
        count = load_stage1_results_to_db(args.load_stage1, db_path)
        LOGGER.info("Loaded municipalities from Stage 1", count=count)

    if args.scrape:
        muni = get_municipality(name=args.scrape, db_path=db_path)
        if muni and muni.get('official_website'):
            results = scraper.scrape_municipality(muni['name'], muni['official_website'])
            LOGGER.info(
                "Scrape results",
                municipality=args.scrape,
                pages_found=len(results['pages_found']),
                documents_found=len(results['documents_found']),
                commitments_found=len(results['commitments']),
            )
            for c in results['commitments']:
                LOGGER.info(
                    "Commitment found",
                    type=c.commitment_type,
                    units=c.total_units,
                    project=c.project_name,
                )
        else:
            LOGGER.warning("Municipality not found or no website", municipality=args.scrape)

    if args.scrape_all:
        results = scraper.scrape_all_municipalities(limit=args.limit)
        total_commitments = sum(len(r.get('commitments', [])) for r in results)
        total_docs = sum(len(r.get('documents_found', [])) for r in results)
        LOGGER.info(
            "Scrape all completed",
            municipalities_scraped=len(results),
            total_commitments=total_commitments,
            total_documents=total_docs,
        )


if __name__ == "__main__":
    main()
