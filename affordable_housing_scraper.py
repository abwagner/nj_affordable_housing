#!/usr/bin/env python3
"""
Stage 2: Affordable Housing Commitment Scraper

This script scrapes municipal websites to find affordable housing commitments,
settlement agreements, and housing plans.
"""

import re
import time
import hashlib
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from pathlib import Path
from dataclasses import dataclass, asdict
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

        # Try to extract structured information
        commitment = AffordableHousingCommitment(
            municipality=municipality,
            source_url=source_url,
        )

        # Extract unit counts using patterns
        unit_patterns = [
            r'(\d+)\s*(?:affordable|low[- ]income|moderate[- ]income)\s*(?:housing\s*)?units?',
            r'(?:affordable|low[- ]income|moderate[- ]income)\s*(?:housing\s*)?units?[:\s]*(\d+)',
            r'(\d+)\s*units?\s*(?:of\s*)?affordable\s*housing',
            r'total\s*(?:of\s*)?(\d+)\s*(?:affordable\s*)?units?',
        ]

        for pattern in unit_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                try:
                    # Take the largest number found (often the total)
                    units = max(int(m) for m in matches if m.isdigit())
                    if units > 0 and units < 10000:  # Sanity check
                        commitment.total_units = units
                        break
                except (ValueError, TypeError):
                    pass

        # Extract commitment types
        if 'settlement agreement' in text_lower or 'settlement' in text_lower:
            commitment.commitment_type = 'Settlement Agreement'
        elif 'coah' in text_lower or 'council on affordable housing' in text_lower:
            commitment.commitment_type = 'COAH'
        elif 'builders remedy' in text_lower or "builder's remedy" in text_lower:
            commitment.commitment_type = 'Builders Remedy'
        elif 'mount laurel' in text_lower:
            commitment.commitment_type = 'Mount Laurel'
        elif 'inclusionary' in text_lower:
            commitment.commitment_type = 'Inclusionary Zoning'

        # Extract year/deadline patterns
        year_patterns = [
            r'by\s*(20\d{2})',
            r'deadline[:\s]*(20\d{2})',
            r'through\s*(20\d{2})',
            r'(20\d{2})\s*(?:deadline|goal|target)',
        ]

        for pattern in year_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                commitment.deadline = matches[0]
                break

        # Extract project names (look for capitalized phrases near "affordable")
        project_pattern = r'(?:the\s+)?([A-Z][A-Za-z\s]+(?:Village|Gardens|Apartments|Commons|Place|Court|Homes|Manor|Towers|Heights|Park|Estate|Ridge|View|Point|Landing))'
        project_matches = re.findall(project_pattern, text)
        if project_matches:
            commitment.project_name = project_matches[0].strip()

        # Store relevant text snippet
        for kw in AFFORDABLE_HOUSING_KEYWORDS:
            idx = text_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 200)
                end = min(len(text), idx + 500)
                commitment.raw_text = text[start:end].strip()
                break

        # Only add if we found something meaningful
        if commitment.total_units or commitment.commitment_type or commitment.project_name:
            commitments.append(commitment)
            LOGGER.info(f"Extracted commitment: {commitment.commitment_type}, "
                       f"{commitment.total_units} units, project: {commitment.project_name}")

        return commitments

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
