#!/usr/bin/env python3
"""
NJ Municipality Website Finder

This script automatically finds the official websites for all NJ municipalities
by searching Google and updating the YAML file with the results.
"""

import yaml
import time
import requests
from urllib.parse import urlparse, quote_plus
import re
from typing import Dict, List, Optional
import structlog
from bs4 import BeautifulSoup

# Set up logging
LOGGER = structlog.get_logger(__name__)

class MunicipalityWebsiteFinder:
    def __init__(self, yaml_file_path: str, output_file_path: str = None):
        self.yaml_file_path = yaml_file_path
        self.output_file_path = output_file_path or yaml_file_path
        self.municipalities = []
        self.website_results = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def load_municipalities(self) -> List[str]:
        """Load municipalities from YAML file."""
        try:
            with open(self.yaml_file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                # Parse the simple list format
                municipalities = [line.strip() for line in content.strip().split('\n') if line.strip()]
                LOGGER.info(f"Loaded {len(municipalities)} municipalities")
                return municipalities
        except Exception as e:
            LOGGER.error(f"Error loading municipalities: {e}")
            return []
    
    def extract_municipality_websites_from_nj_gov(self) -> Dict[str, str]:
        """
        Extract municipality websites from NJ state government's local government directory.
        This is more reliable than Google search as it's an official source.
        """
        nj_gov_url = "https://www.nj.gov/nj/gov/county/localgov.shtml"
        results = {}
        
        try:
            LOGGER.info(f"Fetching municipality websites from NJ state government: {nj_gov_url}")
            
            response = self.session.get(nj_gov_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for municipality links in the page
            # The structure might vary, so we'll try multiple approaches
            municipality_links = []
            
            # Approach 1: Look for links containing municipality names
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                # Check if this looks like a municipality link
                if href.startswith('http') and any(keyword in text.lower() for keyword in ['township', 'borough', 'city', 'town', 'village']):
                    municipality_links.append((text, href))
            
            # Approach 2: Look for links in tables or lists
            tables = soup.find_all('table')
            for table in tables:
                for row in table.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    for cell in cells:
                        links = cell.find_all('a', href=True)
                        for link in links:
                            href = link.get('href', '')
                            text = link.get_text(strip=True)
                            if href.startswith('http') and text.strip():
                                municipality_links.append((text, href))
            
            # Approach 3: Look for any links that might be municipality websites
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                # Filter for likely municipality websites
                if (href.startswith('http') and 
                    any(domain in href.lower() for domain in ['.gov', '.nj.us', '.us', '.org']) and
                    text.strip() and len(text) > 2):
                    municipality_links.append((text, href))
            
            # Remove duplicates and clean up
            unique_links = list(set(municipality_links))
            
            LOGGER.info(f"Found {len(unique_links)} potential municipality links")
            
            # Try to match with our municipality list
            municipalities = self.load_municipalities()
            for municipality in municipalities:
                best_match = self.find_best_municipality_match(municipality, unique_links)
                if best_match:
                    results[municipality] = best_match
                    LOGGER.info(f"Found website for {municipality}: {best_match}")
            
            LOGGER.info(f"Successfully matched {len(results)} municipalities from NJ state government")
            return results
            
        except Exception as e:
            LOGGER.error(f"Error extracting from NJ state government: {e}")
            return {}
    
    def find_best_municipality_match(self, municipality: str, municipality_links: List[tuple]) -> Optional[str]:
        """
        Find the best matching municipality website from the list of links.
        """
        if not municipality_links:
            return None
        
        best_match = None
        best_score = 0
        
        municipality_lower = municipality.lower()
        
        for link_text, link_url in municipality_links:
            score = 0
            link_text_lower = link_text.lower()
            
            # Exact name match gets highest score
            if municipality_lower == link_text_lower:
                score = 100
            # Partial name match
            elif municipality_lower in link_text_lower or link_text_lower in municipality_lower:
                score = 80
            # Word-by-word matching
            else:
                municipality_words = set(municipality_lower.split())
                link_words = set(link_text_lower.split())
                common_words = municipality_words.intersection(link_words)
                if common_words:
                    score = len(common_words) * 20
            
            # Bonus for government domains
            if any(domain in link_url.lower() for domain in ['.gov', '.nj.us', '.us']):
                score += 10
            
            # Bonus for exact municipality name in URL
            if municipality_lower.replace(' ', '').replace('-', '').replace('_', '') in link_url.lower():
                score += 15
            
            if score > best_score:
                best_score = score
                best_match = link_url
        
        # Only return matches with a reasonable score
        if best_score >= 20:
            return best_match
        
        return None
    
    def search_municipality_website(self, municipality: str) -> Optional[str]:
        """
        Search for a municipality's official website using Google.
        Returns the most likely official government website.
        """
        try:
            # Create search query
            search_query = f'"{municipality} NJ" "official website" "government" -wikipedia -facebook -twitter'
            encoded_query = quote_plus(search_query)
            
            # Use Google search
            search_url = f"https://www.google.com/search?q={encoded_query}"
            LOGGER.debug(f"Search URL: {search_url}")
            
            LOGGER.info(f"Searching for: {municipality}")
            
            # Add delay to be respectful to Google
            time.sleep(2)
            
            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()
            
            # Extract URLs from search results using BeautifulSoup
            urls = self.extract_urls_from_google(response.text)
            
            # Find the most likely official website
            official_website = self.find_official_website(urls, municipality)
            
            if official_website:
                LOGGER.info(f"Found website for {municipality}: {official_website}")
            else:
                LOGGER.warning(f"No official website found for {municipality}")
                
            return official_website
            
        except Exception as e:
            LOGGER.error(f"Error searching for {municipality}: {e}")
            return None
    
    def extract_urls_from_google(self, html_content: str) -> List[str]:
        """Extract URLs from Google search results HTML using BeautifulSoup."""
        urls = []
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Look for search result links
            # Google search results typically have links in divs with class 'g' or similar
            search_results = soup.find_all('a', href=True)
            
            for link in search_results:
                href = link.get('href', '')
                
                # Filter out Google's own URLs and extract actual search result URLs
                if href.startswith('/url?q='):
                    # Extract the actual URL from Google's redirect
                    actual_url = href.split('/url?q=')[1].split('&')[0]
                    if actual_url.startswith('http'):
                        urls.append(actual_url)
                elif href.startswith('http') and not any(domain in href.lower() for domain in ['google.com', 'youtube.com', 'facebook.com']):
                    urls.append(href)
            
            # Remove duplicates and limit results
            unique_urls = list(set(urls))[:15]
            LOGGER.debug(unique_urls)
            
            LOGGER.debug(f"Extracted {len(unique_urls)} URLs from search results")
            return unique_urls
            
        except Exception as e:
            LOGGER.error(f"Error parsing HTML: {e}")
            # Fallback to regex if BeautifulSoup fails
            return self.extract_urls_fallback(html_content)
    
    def extract_urls_fallback(self, html_content: str) -> List[str]:
        """Fallback URL extraction using regex if BeautifulSoup fails."""
        urls = []
        
        # Look for common patterns in Google search results
        patterns = [
            r'href="([^"]*)"',
            r'url=([^&]*)',
            r'https?://[^\s"<>]+'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            for match in matches:
                if match.startswith('http'):
                    urls.append(match)
        
        # Remove duplicates and filter out Google's own URLs
        filtered_urls = []
        for url in urls:
            if not any(domain in url.lower() for domain in ['google.com', 'youtube.com', 'facebook.com']):
                filtered_urls.append(url)
        
        LOGGER.debug(filtered_urls)
        
        return list(set(filtered_urls))[:10]
    
    def find_official_website(self, urls: List[str], municipality: str) -> Optional[str]:
        """
        Find the most likely official government website from a list of URLs.
        """
        if not urls:
            return None
        
        # Priority scoring for official government websites
        official_domains = ['.gov', '.nj.us', '.us', '.org']
        municipality_lower = municipality.lower().replace(' ', '').replace('-', '').replace('_', '')
        
        scored_urls = []
        
        for url in urls:
            score = 0
            try:
                domain = urlparse(url).netloc.lower()
                
                # Higher score for government domains
                for gov_domain in official_domains:
                    if gov_domain in domain:
                        score += 10
                
                # Higher score if municipality name is in domain
                if municipality_lower in domain.replace('.', ''):
                    score += 8
                
                # Higher score for .gov domains
                if domain.endswith('.gov'):
                    score += 5
                
                # Higher score for .nj.us domains
                if domain.endswith('.nj.us'):
                    score += 4
                
                # Higher score for .us domains
                if domain.endswith('.us'):
                    score += 3
                
                # Higher score for .org domains (many government sites use .org)
                if domain.endswith('.org'):
                    score += 2
                
                # Lower score for commercial domains
                if any(commercial in domain for commercial in ['.com', '.net']):
                    score -= 2
                
                # Bonus for common government site patterns
                if any(pattern in domain for pattern in ['township', 'borough', 'city', 'town', 'village']):
                    score += 3
                
                scored_urls.append((url, score))
                LOGGER.debug(f"Scored URL: {url} with score: {score}")
                
            except Exception as e:
                LOGGER.error(f"Error parsing URL {url}: {e}")
                continue
        
        # Sort by score and return the highest
        scored_urls.sort(key=lambda x: x[1], reverse=True)
        
        if scored_urls and scored_urls[0][1] > 0:
            return scored_urls[0][0]
        
        # If no good matches, return the first URL that might be official
        for url, score in scored_urls:
            if score >= 0:
                return url
        
        return None
    
    def find_all_websites(self) -> Dict[str, str]:
        """Find websites for all municipalities using multiple approaches."""
        municipalities = self.load_municipalities()
        if not municipalities:
            return {}
        
        results = {}
        total = len(municipalities)
        
        # First, try to get websites from NJ state government (most reliable)
        LOGGER.info("Step 1: Extracting websites from NJ state government directory...")
        nj_gov_results = self.extract_municipality_websites_from_nj_gov()
        results.update(nj_gov_results)
        
        # Then, use Google search for remaining municipalities
        remaining_municipalities = [m for m in municipalities if m not in results]
        LOGGER.info(f"Step 2: Using Google search for {len(remaining_municipalities)} remaining municipalities...")
        
        for i, municipality in enumerate(remaining_municipalities, 1):
            LOGGER.info(f"Processing {i}/{len(remaining_municipalities)}: {municipality}")
            
            website = self.search_municipality_website(municipality)
            if website:
                results[municipality] = website
            
            # Progress update
            if i % 10 == 0:
                LOGGER.info(f"Progress: {i}/{len(remaining_municipalities)} municipalities processed")
        
        return results
    
    def save_results(self, results: Dict[str, str]):
        """Save results to YAML file."""
        try:
            # Create a structured YAML with municipalities and their websites
            yaml_data = {
                'municipalities': {}
            }
            
            for municipality, website in results.items():
                yaml_data['municipalities'][municipality] = {
                    'official_website': website,
                    'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
                }
            
            with open(self.output_file_path, 'w', encoding='utf-8') as file:
                yaml.dump(yaml_data, file, default_flow_style=False, indent=2, allow_unicode=True)
            
            LOGGER.info(f"Results saved to {self.output_file_path}")
            
        except Exception as e:
            LOGGER.error(f"Error saving results: {e}")
    
    def run(self):
        """Main execution method."""
        LOGGER.info("Starting NJ Municipality Website Finder")
        
        # Find all websites
        results = self.find_all_websites()
        
        # Save results
        self.save_results(results)
        
        # Summary
        LOGGER.info(f"Process completed. Found websites for {len(results)} out of {len(self.load_municipalities())} municipalities")
        
        return results

def main():
    """Main function."""
    finder = MunicipalityWebsiteFinder(
        yaml_file_path='nj_municipalities.yaml',
        output_file_path='nj_municipalities_with_websites.yaml'
    )
    
    results = finder.run()
    
    # Print summary
    print("\n" + "="*50)
    print("NJ MUNICIPALITY WEBSITE FINDER - RESULTS")
    print("="*50)
    print(f"Total municipalities processed: {len(finder.load_municipalities())}")
    print(f"Websites found: {len(results)}")
    print(f"Success rate: {(len(results) / len(finder.load_municipalities()) * 100):.1f}%")
    
    if results:
        print("\nSample results:")
        for i, (municipality, website) in enumerate(list(results.items())[:5]):
            print(f"  {municipality}: {website}")
        if len(results) > 5:
            print(f"  ... and {len(results) - 5} more")

if __name__ == "__main__":
    main()
