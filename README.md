# NJ Municipality Website Finder

This script automatically finds the official websites for all NJ municipalities by searching Google and updating a YAML file with the results.

## Features

- **Automated Search**: Searches Google for each municipality's official website
- **Smart Filtering**: Prioritizes government domains (.gov, .nj.us, .us, .org)
- **Rate Limiting**: Includes delays to be respectful to search engines
- **Robust Parsing**: Uses BeautifulSoup for reliable HTML parsing with regex fallback
- **Structured Output**: Saves results in organized YAML format with timestamps

## Requirements

- Python 3.7+
- Required packages (see requirements.txt)

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Ensure your municipalities file is ready:**
   - The script expects `nj_municipalities.yaml` in the same directory
   - Each municipality should be on a separate line

## Usage

### Basic Usage

```bash
python municipality_website_finder.py
```

### What It Does

1. **Loads** municipalities from `nj_municipalities.yaml`
2. **Searches** Google for each municipality + "NJ official website government"
3. **Filters** results to find the most likely official government website
4. **Scores** URLs based on domain type and municipality name matching
5. **Saves** results to `nj_municipalities_with_websites.yaml`

### Output Format

The script creates a structured YAML file:

```yaml
municipalities:
  Newark:
    official_website: https://www.newarknj.gov
    last_updated: "2024-01-15 14:30:25"
  Jersey City:
    official_website: https://jerseycitynj.gov
    last_updated: "2024-01-15 14:30:45"
  # ... and so on
```

## Configuration

### Search Query Customization

You can modify the search query in the `search_municipality_website` method:

```python
search_query = f'"{municipality} NJ" "official website" "government" -wikipedia -facebook -twitter'
```

### Scoring System

The script uses a scoring system to identify official websites:

- **+10 points** for government domains (.gov, .nj.us, .us, .org)
- **+8 points** if municipality name appears in domain
- **+5 points** for .gov domains
- **+4 points** for .nj.us domains
- **+3 points** for .us domains
- **+2 points** for .org domains
- **+3 points** for government-related keywords (township, borough, city, town, village)
- **-2 points** for commercial domains (.com, .net)

## Important Notes

### Rate Limiting

- **2-second delay** between searches to be respectful to Google
- Consider running during off-peak hours for large lists
- The script processes ~30 municipalities per minute

### Google Search Limitations

- Google may temporarily block requests if too many are made
- Consider using a VPN or running in smaller batches
- The script includes error handling for failed requests

### Accuracy

- **Expected success rate**: 70-90% for official websites
- Some municipalities may not have websites or may use non-standard domains
- Results should be manually verified for critical applications

## Troubleshooting

### Common Issues

1. **"No module named 'bs4'"**
   - Run: `pip install beautifulsoup4`

2. **"No module named 'yaml'"**
   - Run: `pip install PyYAML`

3. **Google blocking requests**
   - Wait a few hours and try again
   - Consider using a different IP address
   - Reduce the number of municipalities processed at once

4. **Low success rate**
   - Check if Google search is working in your browser
   - Verify your internet connection
   - Some municipalities may genuinely not have websites

### Manual Verification

After running the script, you may want to:

1. **Spot-check** a few results in your browser
2. **Verify** that the domains are actually government sites
3. **Update** any incorrect results manually in the YAML file

## Example Results

The script successfully finds websites like:
- Newark: `https://www.newarknj.gov`
- Jersey City: `https://jerseycitynj.gov`
- Paterson: `https://patersonnj.gov`
- Elizabeth: `https://elizabethnj.org`

## License

This script is provided as-is for educational and research purposes. Please use responsibly and respect website terms of service.
