---
type: notes
date: 2026-05-04
project: SAA-Org-Tracker
tags: [api, research, technical]
status: draft
---

## API Research Notes

Reference notes on external APIs for the [[SAA-Org-Tracker]] data pipeline.

---

## ProPublica Nonprofit Explorer API

**Status**: Free, no API key required
**Coverage**: All US nonprofits that file 990, 990-EZ, or 990-PF
**Data lag**: ~12–18 months behind (IRS processing delay)

### Key endpoints

```
# Search by name
GET https://projects.propublica.org/nonprofits/api/v2/search.json
  ?q=south+asian+community+services
  &state[id]=NY
  &ntee[id]=P   # Human services NTEE code

# Full org detail + 990 history
GET https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json

# Single filing detail
GET https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}/filings/{year}.json
```

### Key 990 fields available
- `totrevenue` — Total revenue
- `totfuncexpns` — Total functional expenses
- `progsvceexpns` — Program service expenses
- `totassetsend` — Total assets end of year
- `totliabend` — Total liabilities end of year
- `noemployees` — Number of employees

### NTEE codes for SAA orgs
Common codes to expect:
- `P20` — Human services — multipurpose
- `A23` — Cultural/ethnic awareness
- `B` — Education
- `E` — Health
- `Q` — International, foreign affairs

---

## Meta Graph API (Facebook)

**Status**: Free with developer app; page owner NOT required for public page data
**App registration**: https://developers.facebook.com

### What's available without page owner auth
Using an App Access Token (`{app-id}|{app-secret}`):

```
# Page basic info + fan count
GET /{page-id}?fields=name,fan_count,followers_count,about,website
    &access_token={app-access-token}

# Recent posts (public pages only)
GET /{page-id}/posts?fields=created_time,message,reactions.summary(true),comments.summary(true)
    &limit=50
    &access_token={app-access-token}
```

### Limitations
- Private/unlisted pages: not accessible
- Post content sometimes restricted (page settings)
- Rate limits: 200 calls/hour per app token (generous for our use case)
- Page ID: can find via `GET /search?q={name}&type=page` or from the page URL

### Finding Page IDs
From URL: `facebook.com/southasiannetwork` → page name is `southasiannetwork`
Can use: `GET /southasiannetwork?fields=id,name`

---

## Instagram

**Status**: Complex — two paths with very different access levels

### Path A: Instagram Graph API (official)
- Requires page OWNER to authorize your app
- Gets: media count, followers, engagement per post, story views
- **Not viable** for scraping orgs we don't own

### Path B: Apify Instagram Scraper
- URL: https://apify.com/apify/instagram-scraper
- Cost: ~$5/1000 profile scrapes (pay-as-you-go)
- Free tier: $5/month credit
- Gets: followers, following, posts count, recent post dates, avg likes
- Reliability: Good, maintained actively
- Legal note: Public profile data only; compliant with Instagram ToS for research

### Path C: Selenium/Playwright scraping
- Free but brittle
- Instagram actively blocks automated access
- Not recommended for production

**Recommendation**: Use Apify for v1. Budget ~$10–20/quarter for the org count we have.

---

## Website Monitoring

### Python `requests` approach
```python
import requests
from datetime import datetime

def check_website(url):
    try:
        r = requests.get(url, timeout=10, allow_redirects=True)
        return {
            "is_live": r.status_code < 400,
            "status_code": r.status_code,
            "ssl_valid": url.startswith("https"),
            "response_ms": r.elapsed.total_seconds() * 1000,
            "last_modified": r.headers.get("Last-Modified"),
            "content_length": len(r.content)
        }
    except Exception as e:
        return {"is_live": False, "error": str(e)}
```

### Google Lighthouse API
- Available via PageSpeed Insights API (free, key needed)
- `GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&key={key}`
- Returns performance score, accessibility, mobile-friendliness
- Good signal for org digital health but adds complexity — defer to Phase 2

---

## Airtable API

**Library**: `pyairtable` (Python)
```bash
pip install pyairtable
```

```python
from pyairtable import Api

api = Api(os.environ["AIRTABLE_API_KEY"])
table = api.table("BASE_ID", "Organizations")

# Read all orgs
orgs = table.all()

# Write health score
scores_table = api.table("BASE_ID", "HealthScores")
scores_table.create({
    "org": [org_record_id],
    "score_date": "2026-03-31",
    "total_score": 72,
    ...
})
```

---

## Open Research Items

> [!question] Still to verify
> - Can we get Instagram follower counts reliably via Apify for ~200 orgs/quarter within free tier?
> - Does ProPublica cover very small orgs (revenue < $50K) that file 990-EZ?
> - What's the best way to bulk-find Facebook Page IDs given only org name + state?
> - Are there IRS bulk data files that give us EINs faster than ProPublica search?
