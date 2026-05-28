---
type: spec
date: 2026-05-04
project: SAA-Org-Tracker
status: draft
tags: [architecture, system-design]
---

## System Architecture

Full architecture for the [[SAA-Org-Tracker]] — a hybrid system combining Airtable as the data backbone with a lightweight custom layer for the health scoring pipeline and a no-code public directory.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     PUBLIC DIRECTORY                        │
│                    Softr (no-code)                          │
│         Search · Filter · Org profiles · Health badges      │
└─────────────────────┬───────────────────────────────────────┘
                      │ Airtable connector
┌─────────────────────▼───────────────────────────────────────┐
│                   AIRTABLE (Source of Truth)                │
│  Organizations │ HealthScores │ SocialMetrics │ FinancialData│
└──┬────────────────────────────────────────┬─────────────────┘
   │ read orgs                              │ write scores
   │                              ┌─────────▼─────────────────┐
   │                              │    SCORING ENGINE         │
   │                              │    Python · quarterly     │
   │                              │    Weighted composite     │
   │                              │    0–100 per org          │
   │                              └─────────┬─────────────────┘
   │                                        │ aggregates from
┌──▼────────────────────────────────────────▼─────────────────┐
│                    DATA PIPELINE                            │
│              Python scripts · GitHub Actions                │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Website    │  │   Social     │  │   Financial      │  │
│  │   Monitor    │  │   Crawler    │  │   Fetcher        │  │
│  │              │  │              │  │                  │  │
│  │ requests     │  │ Meta Graph   │  │ ProPublica API   │  │
│  │ Lighthouse   │  │ API + Apify  │  │ IRS 990 bulk     │  │
│  │              │  │ fallback     │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Airtable Schema

### Existing Table: `Organizations`
Fields to ADD to the existing table:

| Field | Type | Notes |
|---|---|---|
| `ein` | Text | IRS Employer ID — key to 990 data |
| `fb_page_id` | Text | Facebook Page ID for Graph API |
| `ig_handle` | Text | Instagram handle (without @) |
| `airtable_record_id` | Formula | Auto — for pipeline joins |
| `current_health_score` | Rollup | Latest score from HealthScores table |
| `health_tier` | Formula | 🟢/🟡/🟠/🔴 based on score |
| `last_scored_date` | Date | When pipeline last ran |

### New Table: `HealthScores`
Quarterly snapshots per organization.

| Field | Type | Notes |
|---|---|---|
| `org` | Link → Organizations | |
| `score_date` | Date | Quarter end date |
| `total_score` | Number (0–100) | Composite |
| `presence_score` | Number (0–100) | Domain: digital presence |
| `activity_score` | Number (0–100) | Domain: content activity |
| `reach_score` | Number (0–100) | Domain: community reach |
| `financial_score` | Number (0–100) | Domain: financial health |
| `health_tier` | Select | Healthy / Stable / At Risk / Critical |
| `qoq_change` | Number | Score delta from prior quarter |
| `trend` | Select | Improving / Stable / Declining |
| `notes` | Long text | Pipeline run notes, data gaps |

### New Table: `SocialMetrics`
Raw social snapshots (collected weekly or monthly, used in quarterly score).

| Field | Type | Notes |
|---|---|---|
| `org` | Link → Organizations | |
| `collected_date` | Date | |
| `platform` | Select | Facebook / Instagram / Website |
| `followers` | Number | |
| `following` | Number | |
| `posts_30d` | Number | Posts in last 30 days |
| `posts_90d` | Number | Posts in last 90 days |
| `last_post_date` | Date | |
| `engagement_rate` | Number | Avg engagements per post / followers |
| `avg_likes` | Number | |
| `avg_comments` | Number | |
| `raw_data` | Long text | JSON blob for reference |

### New Table: `FinancialMetrics`
Annual 990 data per organization.

| Field | Type | Notes |
|---|---|---|
| `org` | Link → Organizations | |
| `tax_year` | Number | e.g., 2023 |
| `total_revenue` | Currency | |
| `total_expenses` | Currency | |
| `program_expenses` | Currency | Service delivery costs |
| `net_assets` | Currency | |
| `program_expense_ratio` | Formula | program_expenses / total_expenses |
| `revenue_yoy_change` | Number | % change from prior year |
| `num_employees` | Number | FTE count from 990 |
| `data_source` | Select | ProPublica / IRS Bulk / Manual |
| `filing_date` | Date | When 990 was filed |

---

## Layer 2 — Data Pipeline

### Script: `website_monitor.py`
Runs: Monthly

```
For each org with a website URL:
  1. HTTP GET — capture status code, response time, SSL validity
  2. Check for contact page (look for /contact, /about patterns)
  3. Parse last-modified header or sitemap date
  4. Run Lighthouse API for performance score (optional)
  5. Write to SocialMetrics table (platform = "Website")
```

**Signals captured**: is_live (bool), ssl_valid (bool), response_ms, last_updated, has_contact_page

### Script: `social_crawler.py`
Runs: Monthly (weekly for high-priority orgs)

**Facebook (Meta Graph API)**:
- Public page data available with app access token (no page owner needed)
- Endpoint: `GET /{page-id}?fields=fan_count,posts{created_time,reactions,comments}`
- Requires: Meta Developer App (free) → App Access Token
- Gets: fan_count, post dates (last 30/90 days), reaction counts

**Instagram**:
- Business/Creator accounts require owner auth (Instagram Graph API)
- Fallback: Apify's Instagram Scraper actor (~$5/1000 profiles) or free tier
- Gets: followers, posts, avg likes/comments

**EIN-to-Page matching**: Store `fb_page_id` in Airtable during data entry; can also search by org name via Facebook Graph Search.

### Script: `financial_fetcher.py`
Runs: Quarterly (990 data lags 12–18 months, so quarterly is sufficient)

**ProPublica Nonprofit Explorer API** (free, no key needed):
```
GET https://projects.propublica.org/nonprofits/api/v2/search.json?q={org_name}&state[id]={state}
→ Returns EIN, name, revenue, ntee_code, filings list

GET https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json
→ Returns full 990 history
```

**EIN Matching strategy**:
1. Manual: staff enters EIN during org data entry (best)
2. Automated: fuzzy name match against ProPublica search results, flag for human review
3. Unincorporated orgs: score financial domain as N/A (adjust weight accordingly)

### Script: `scoring_engine.py`
Runs: Quarterly (after all collectors have run)

```python
# Pseudo-code for composite score

def score_org(org_id, as_of_date):
    social = get_latest_social_metrics(org_id, as_of_date)
    financial = get_latest_financial_metrics(org_id)
    
    # Domain 1: Digital Presence (25%)
    presence = score_presence(
        website_live=social.website.is_live,
        ssl_valid=social.website.ssl_valid,
        has_facebook=org.fb_page_id is not None,
        has_instagram=org.ig_handle is not None,
        has_contact_page=social.website.has_contact_page
    )
    
    # Domain 2: Content Activity (30%)
    activity = score_activity(
        fb_posts_30d=social.facebook.posts_30d,
        ig_posts_30d=social.instagram.posts_30d,
        days_since_last_post=social.days_since_last_post,
        website_freshness_days=social.website.days_since_updated
    )
    
    # Domain 3: Community Reach (25%)
    reach = score_reach(
        total_followers=social.total_followers,
        follower_growth_pct=social.follower_growth_qoq,
        engagement_rate=social.avg_engagement_rate
    )
    
    # Domain 4: Financial Health (20%)  
    financial_score = score_financial(
        revenue_trend=financial.revenue_yoy_change,
        program_ratio=financial.program_expense_ratio,
        net_assets=financial.net_assets,
        filing_recency=financial.days_since_filing
    ) if financial else None
    
    # Composite — reweight if financial N/A
    weights = get_weights(has_financial=financial is not None)
    total = weighted_average([presence, activity, reach, financial_score], weights)
    
    return HealthScore(total=total, presence=presence, activity=activity,
                       reach=reach, financial=financial_score)
```

---

## Layer 3 — Automation (GitHub Actions)

```yaml
# .github/workflows/health-pipeline.yml

on:
  schedule:
    - cron: '0 6 1 * *'   # Monthly: website + social collectors
    - cron: '0 6 1 1,4,7,10 *'  # Quarterly: financial + scoring engine
  workflow_dispatch:  # Manual trigger

jobs:
  collect-social:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
      - run: pip install pyairtable requests apify-client
      - run: python pipeline/website_monitor.py
      - run: python pipeline/social_crawler.py
      
  score-quarterly:
    needs: collect-social
    runs-on: ubuntu-latest
    steps:
      - run: python pipeline/financial_fetcher.py
      - run: python pipeline/scoring_engine.py
```

Secrets stored in GitHub repo: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `META_APP_TOKEN`, `APIFY_TOKEN`

---

## Layer 4 — Public Directory (Softr)

Softr reads directly from Airtable. Configuration:

- **List view**: All orgs, searchable by name/location/service type
- **Filter sidebar**: State, community served, service category, health tier
- **Org profile page**: Full org detail — description, website link, social links, health badge
- **Health badge**: Simple 🟢/🟡/🟠/🔴 indicator (detailed score kept internal initially)
- **"How to help" section**: Link to website/donate/volunteer for each org

Airtable view to expose in Softr: Create a filtered view that excludes internal fields (raw API data, EINs, etc.)

---

## Phase Plan

### Phase 1 (Weeks 1–4): Foundation
- [ ] Extend Airtable schema (add EIN, social IDs, new tables)
- [ ] Set up Softr directory connected to Airtable
- [ ] Register Meta Developer app, get Graph API token
- [ ] Write and test `website_monitor.py` against 10 orgs
- [ ] Write and test `financial_fetcher.py` against known EINs

### Phase 2 (Weeks 5–8): Pipeline
- [ ] Write and test `social_crawler.py` (Facebook first, Instagram second)
- [ ] Write `scoring_engine.py` with initial weights
- [ ] Run full pipeline against 20–30 orgs, calibrate scores
- [ ] Wire GitHub Actions automation

### Phase 3 (Weeks 9–12): Polish & Launch
- [ ] Calibrate scoring model against ground truth (known healthy vs. struggling orgs)
- [ ] Publish Softr directory
- [ ] Internal dashboard for health score trends
- [ ] Quarterly report template for stakeholders/funders

---

## Risk Register

> [!warning] Key risks
> - **Instagram API access**: Without page-owner auth, must rely on scraping. Apify is reliable but adds cost. Monitor for policy changes.
> - **990 data lag**: Financial data is 12–18 months behind reality. Score model should weight this accordingly — treat it as a lagging indicator, not leading.
> - **EIN coverage**: Small unincorporated orgs (temples, cultural clubs) may have no EIN and no 990. Plan: score financial domain as N/A and reweight.
> - **Score gaming**: Once scores are public, orgs could post low-quality content just to boost activity score. Mitigate with engagement rate weighting.
> - **Meta API stability**: Facebook Graph API has changed significantly over the years. Build with abstraction layer so you can swap data source.
