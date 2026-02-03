# NJ Affordable Housing Tracker

This project tracks affordable housing commitments by New Jersey municipalities and determines the status of those commitments through news articles and satellite imagery analysis. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full roadmap.

## Project Overview

**Goal:** Create transparency around NJ affordable housing development by:
1. Identifying municipal affordable housing commitments
2. Tracking the status of those commitments
3. Verifying actual development through satellite imagery

**Current Status:**
- **Stage 1 (Complete):** Municipality website discovery
- **Stage 2 (Partial):** Affordable housing commitment scraper and database

## Requirements

- Python 3.10+
- Required packages: `pip install -r requirements.txt`

## Stage 1: Municipality Website Finder

Finds official websites for all 565 NJ municipalities using NJ.gov directory and Google search fallback.

### Usage

```bash
python municipality_website_finder.py
```

### Input/Output

- **Input:** `nj_municipalities.yaml` — plain list, one municipality per line
- **Output:** `nj_municipalities_with_websites.yaml` — municipality → website mappings

### Features

- Dual-source approach (NJ.gov scraping + Google search fallback)
- Smart matching to avoid wrong assignments (e.g., Asbury Park vs Cliffside Park)
- Rate limiting and respectful delays

---

## Stage 2: Affordable Housing Scraper

Scrapes municipal websites for affordable housing commitments, plans, and obligations.

### Database Setup

```bash
# Initialize the database
python database.py --init

# Load Stage 1 results (municipality websites) into the database
python affordable_housing_scraper.py --load-stage1 nj_municipalities_with_websites.yaml
```

### Scraping

```bash
# Scrape a specific municipality
python affordable_housing_scraper.py --scrape "Newark"

# Scrape all municipalities (optionally limit)
python affordable_housing_scraper.py --scrape-all
python affordable_housing_scraper.py --scrape-all --limit 10

# Use a custom database path
python affordable_housing_scraper.py --db /path/to/db.sqlite --scrape-all
```

### Database Stats

```bash
python database.py --stats
```

---

## Running Tests

```bash
# Run all tests
python -m pytest -v

# Run specific test modules
python -m pytest test_municipality_website_finder.py -v
python -m pytest test_database.py -v
python -m pytest test_affordable_housing_scraper.py -v
```

---

## Project Structure

| File | Description |
|------|-------------|
| `municipality_website_finder.py` | Stage 1: Discover municipal websites |
| `affordable_housing_scraper.py` | Stage 2: Scrape housing commitments |
| `database.py` | SQLite database operations |
| `nj_municipalities.yaml` | Input: list of 565 NJ municipalities |
| `nj_municipalities_with_websites.yaml` | Stage 1 output |
| `nj_affordable_housing.db` | SQLite database (created on init) |
| `PROJECT_PLAN.md` | Full project roadmap and schema |

---

## Logging

The project uses [structlog](https://www.structlog.org/). By default, logs go to structlog's configured output. For development, you can configure structlog to print to the console or set `STRUCTLOG_*` environment variables.

---

## Important Notes

### Rate Limiting

- **2-second delay** between Google searches in Stage 1
- **1.5-second delay** between page fetches in Stage 2
- Consider running during off-peak hours for large batches

### Data Quality

- Stage 1 results should be spot-checked; some municipalities may have incorrect or shared websites
- Stage 2 extraction uses regex patterns; complex documents may require manual review

### License

This project is provided as-is for educational and research purposes. Use responsibly and respect website terms of service.
