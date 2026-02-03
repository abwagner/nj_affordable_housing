# NJ Affordable Housing Tracker - Project Plan

## Project Overview

This project tracks affordable housing commitments by New Jersey municipalities and determines the status of those commitments through news articles and satellite imagery analysis.

**Goal:** Create transparency around NJ affordable housing development by:
1. Identifying municipal affordable housing commitments
2. Tracking the status of those commitments
3. Verifying actual development through satellite imagery

---

## Stage 1: Municipality Website Discovery ✅ COMPLETE

**Status:** Complete

**Deliverables:**
- `municipality_website_finder.py` - Discovers official websites for all 565 NJ municipalities
- Dual-source approach (NJ.gov scraping + Google search fallback)
- YAML output with municipality → website mappings

**Output:** List of official municipal websites to scrape for housing data

---

## Stage 2: Affordable Housing Commitment Extraction

**Status:** Not Started

**Objective:** Scrape municipal websites to identify affordable housing commitments, plans, and obligations.

### 2.1 Data Sources to Target
- Municipal planning board documents
- Zoning board decisions
- Housing element and fair share plans
- Settlement agreements with COAH (Council on Affordable Housing)
- Court-mandated housing obligations
- Redevelopment plans

### 2.2 Key Information to Extract
| Field | Description |
|-------|-------------|
| Municipality | Township/borough name |
| Commitment Type | COAH settlement, court order, voluntary, etc. |
| Total Units Committed | Number of affordable units promised |
| Unit Breakdown | Low/moderate income split, senior, family, etc. |
| Deadline | Target completion date |
| Developer | Assigned developer (if any) |
| Location | Planned development location/address |
| Document URL | Source document link |
| Date Announced | When commitment was made |

### 2.3 Technical Approach
- [ ] Build web scraper for municipal websites
- [ ] Implement PDF text extraction (many documents are PDFs)
- [ ] Use keyword detection for affordable housing terms
- [ ] NLP/LLM assistance for structured data extraction
- [ ] Store results in structured database (SQLite or PostgreSQL)

### 2.4 Supplementary Data Sources
- NJ Courts - Housing settlement agreements
- NJ Department of Community Affairs - COAH data
- Fair Share Housing Center - Tracking reports
- NJ Future - Housing data compilations

### 2.5 Deliverables
- `affordable_housing_scraper.py` - Web scraper for municipal sites
- `pdf_extractor.py` - PDF document parser
- `commitments_db/` - Database of extracted commitments
- Data schema documentation

---

## Stage 3: News Article Analysis

**Status:** Not Started

**Objective:** Monitor news sources to track the status of affordable housing projects.

### 3.1 News Sources to Monitor
- Local newspapers (NJ.com, TAPinto, Patch, etc.)
- Municipal news feeds
- Real estate news outlets
- Construction/development trade publications

### 3.2 Status Categories to Track
| Status | Description |
|--------|-------------|
| Announced | Commitment made, no construction |
| Planning | In planning/approval process |
| Approved | Permits approved |
| Under Construction | Active construction |
| Completed | Development finished |
| Delayed | Behind schedule |
| Stalled | No progress, unclear status |
| Cancelled | Project abandoned |

### 3.3 Technical Approach
- [ ] Build news aggregator for relevant sources
- [ ] Implement article search by municipality + "affordable housing"
- [ ] Use NLP for sentiment and status extraction
- [ ] Match articles to known commitments
- [ ] Track status changes over time

### 3.4 Deliverables
- `news_aggregator.py` - News source scraper
- `article_analyzer.py` - NLP-based article analysis
- `status_tracker.py` - Timeline and status tracking
- News article database with links to commitments

---

## Stage 4: Satellite Imagery Verification

**Status:** Not Started

**Objective:** Use satellite/aerial imagery to verify actual construction status.

### 4.1 Data Sources
- Google Earth Engine (historical imagery)
- Mapbox Satellite
- NJGIN (NJ Geographic Information Network)
- County GIS portals
- Planet Labs (if budget allows)

### 4.2 Analysis Approach
| Method | Use Case |
|--------|----------|
| Change Detection | Compare before/after imagery for construction activity |
| Building Footprints | Detect new structures at committed locations |
| Timeline Analysis | Track construction progress over time |
| Manual Review | Human verification of automated detections |

### 4.3 Technical Approach
- [ ] Geocode committed development locations
- [ ] Pull historical satellite imagery
- [ ] Implement change detection algorithm
- [ ] Build comparison visualization tool
- [ ] Generate construction verification reports

### 4.4 Deliverables
- `geocoder.py` - Address to coordinates converter
- `imagery_fetcher.py` - Satellite image retrieval
- `change_detector.py` - Image analysis for construction
- Verification reports with imagery comparisons

---

## Stage 5: Dashboard & Reporting

**Status:** Not Started

**Objective:** Create user-friendly interface for exploring affordable housing data.

### 5.1 Dashboard Features
- Interactive map of NJ with commitment locations
- Municipality-level summary cards
- Status filtering (completed, under construction, stalled, etc.)
- Timeline views showing progress
- Comparison of commitments vs. completed units
- Satellite imagery before/after views

### 5.2 Reports to Generate
- Statewide affordable housing progress report
- Municipality scorecards
- "At risk" projects (delayed/stalled)
- Success stories (completed projects)
- Data export (CSV, JSON, API)

### 5.3 Technical Approach
- [ ] Build REST API for data access
- [ ] Create web dashboard (React or Streamlit)
- [ ] Implement map visualization (Leaflet/Mapbox)
- [ ] Add automated report generation
- [ ] Set up public data export

### 5.4 Deliverables
- `api/` - REST API for data access
- `dashboard/` - Web application
- `reports/` - Automated report generation
- Public documentation and data dictionary

---

## Data Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Pipeline                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Stage 1          Stage 2           Stage 3        Stage 4      │
│  ┌──────┐        ┌──────────┐      ┌────────┐    ┌──────────┐  │
│  │ Muni │───────▶│ Housing  │◀────▶│ News   │    │ Satellite│  │
│  │ Sites│        │Commitments│      │Articles│    │ Imagery  │  │
│  └──────┘        └────┬─────┘      └───┬────┘    └────┬─────┘  │
│                       │                │              │         │
│                       ▼                ▼              ▼         │
│                  ┌─────────────────────────────────────┐        │
│                  │         Central Database            │        │
│                  │  - Municipalities                   │        │
│                  │  - Commitments                      │        │
│                  │  - Status Updates                   │        │
│                  │  - News Articles                    │        │
│                  │  - Imagery Analysis                 │        │
│                  └──────────────┬──────────────────────┘        │
│                                 │                               │
│                                 ▼                               │
│                  ┌─────────────────────────────────────┐        │
│                  │    Stage 5: Dashboard & Reports     │        │
│                  └─────────────────────────────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema (Draft)

```sql
-- Municipalities (from Stage 1)
municipalities (
    id, name, county, official_website, population, last_scraped
)

-- Housing Commitments (Stage 2)
commitments (
    id, municipality_id, commitment_type, total_units,
    low_income_units, moderate_income_units, deadline,
    developer, location_address, location_lat, location_lng,
    source_document_url, date_announced, created_at
)

-- Status Updates (Stage 3 & 4)
status_updates (
    id, commitment_id, status, source_type, source_url,
    notes, verified_date, created_at
)

-- News Articles (Stage 3)
news_articles (
    id, commitment_id, title, url, source_name,
    publish_date, extracted_status, summary, created_at
)

-- Imagery Analysis (Stage 4)
imagery_analyses (
    id, commitment_id, imagery_date, imagery_source,
    construction_detected, confidence_score, image_url,
    notes, created_at
)
```

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| Web Scraping | requests, BeautifulSoup, Selenium (JS sites) |
| PDF Extraction | PyPDF2, pdfplumber, or Apache Tika |
| NLP/Text Analysis | spaCy, or LLM API (Claude/GPT) |
| Database | SQLite (dev) → PostgreSQL (prod) |
| Satellite Imagery | Google Earth Engine, rasterio |
| Image Analysis | OpenCV, or computer vision API |
| API Framework | FastAPI or Flask |
| Dashboard | Streamlit (MVP) or React (production) |
| Mapping | Folium, Leaflet, or Mapbox |
| Deployment | Docker, cloud hosting TBD |

---

## Risk & Mitigation

| Risk | Mitigation |
|------|------------|
| Municipal websites vary wildly in structure | Build flexible scrapers, manual fallback |
| PDFs are inconsistent/scanned images | OCR pipeline, manual review queue |
| News articles hard to match to projects | LLM-assisted entity matching |
| Satellite imagery access costs | Start with free tiers, prioritize high-value sites |
| Google/news sites block scraping | Rate limiting, rotating proxies, API access |
| Data becomes stale | Scheduled refresh jobs, change monitoring |

---

## Milestones

### Phase 1: Foundation (Current)
- [x] Stage 1: Municipality website discovery
- [ ] Set up database infrastructure
- [ ] Define data schemas

### Phase 2: Data Collection
- [ ] Stage 2: Build commitment scraper
- [ ] Stage 2: Extract commitments from top 50 municipalities
- [ ] Stage 2: Scale to all 565 municipalities

### Phase 3: Status Tracking
- [ ] Stage 3: News aggregator MVP
- [ ] Stage 3: Article analysis pipeline
- [ ] Stage 4: Geocoding and imagery retrieval

### Phase 4: Verification & Visualization
- [ ] Stage 4: Change detection implementation
- [ ] Stage 5: Basic dashboard MVP
- [ ] Stage 5: Public API

### Phase 5: Production
- [ ] Full data refresh automation
- [ ] Public launch
- [ ] Documentation and data dictionary

---

## Open Questions

1. **Scope prioritization:** Should we focus on specific counties first, or all 565 municipalities?
2. **LLM usage:** Use Claude API for document/article analysis, or build custom NLP?
3. **Imagery budget:** What's the budget for satellite imagery APIs?
4. **Update frequency:** How often should data be refreshed?
5. **Public vs. internal:** Is this for public transparency or internal research?

---

## Next Steps (Immediate)

1. **Run Stage 1** on all municipalities and generate website list
2. **Design database schema** and set up SQLite
3. **Research top data sources** for affordable housing commitments
4. **Prototype Stage 2 scraper** on 5-10 municipalities
5. **Evaluate LLM options** for document analysis

---

*Last Updated: 2026-02-03*
