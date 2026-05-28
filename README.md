---
type: project
status: planning
date: 2026-05-04
tags: [civic-tech, nonprofit, community, south-asian, analytics]
priority: high
---

## Overview

A civic tech platform that discovers, catalogs, and tracks the institutional health of South Asian American organizations across the United States. Two interlocking systems: a **public-facing directory** where community members can find and connect with orgs, and a **health monitoring engine** that scores organizational vitality on a quarterly basis to surface which institutions are thriving or at risk.

## Problem Statement

South Asian American community organizations are largely invisible to the communities they serve and to potential funders/supporters. There's no aggregated view of which orgs exist, what they do, whether they're still active, or whether they're healthy. Resources flow poorly. Organizations fail quietly. Gaps go unnoticed.

## Strategic Goals

- Surface the full landscape of SAA organizations in a searchable, public repository
- Build a composite health score (digital presence + social activity + financial health) tracked quarterly
- Identify at-risk organizations and geographic/service gaps so resources can be directed effectively
- Create a durable data asset for community researchers, funders, and advocates

## Current State

- [[Airtable]] database exists with org records: name, classification, communities served, service types, website, Facebook, Instagram
- Architecture designed (see [[specs/architecture]])
- Data pipeline design: in progress

## Tech Stack

| Layer | Tool | Rationale |
|---|---|---|
| Source of truth | Airtable | Already built; good API; no-code friendly |
| Public directory | Softr | Native Airtable integration; no-code; free tier sufficient |
| Data pipeline | Python (GitHub Actions) | Low-ops scheduled jobs; free tier for personal project |
| Social data | Meta Graph API + Apify fallback | Public page data for Facebook; scraping fallback for Instagram |
| Financial data | ProPublica Nonprofit Explorer API | Free, covers all 990 filers, search by org name |
| Website monitoring | Python `requests` + Lighthouse API | Liveness + basic health signals |
| Scoring engine | Python | Weighted composite across 4 health domains |
| Analytics | Airtable dashboards + optional Metabase | Internal trend views |

## Health Score Model

Four domains, 0–100 composite:

| Domain | Weight | Signals |
|---|---|---|
| Digital Presence | 25% | Website live, SSL valid, social profiles exist, contact info present |
| Content Activity | 30% | Post frequency (30/90 day), recency of last post, website freshness |
| Community Reach | 25% | Follower count, follower growth QoQ, engagement rate |
| Financial Health | 20% | Revenue trend, program expense ratio, net assets, 990 filing recency |

**Score tiers**: 🟢 Healthy (75–100) · 🟡 Stable (50–74) · 🟠 At Risk (25–49) · 🔴 Critical (0–24)

## Key Milestones

- [ ] Finalize Airtable schema extensions (add EIN, FB page ID, IG handle fields)
- [ ] Stand up Softr directory on top of existing Airtable
- [ ] Build 990 fetcher using ProPublica API + EIN matching
- [ ] Build social metrics collector (Facebook Graph API)
- [ ] Build website liveness monitor
- [ ] Wire scoring engine + write scores back to Airtable
- [ ] Schedule quarterly runs via GitHub Actions
- [ ] Launch public directory v1

## Next Steps

> [!todo] Immediate actions
> 1. Export current Airtable schema so we can design the extension tables
> 2. Register a Meta Developer app to get a Graph API token
> 3. Set up ProPublica API test call against a known SAA org (find EIN)
> 4. Create Softr account and connect to Airtable

## Open Questions

> [!question] Open items
> - How do we handle orgs with no EIN (unincorporated community groups)?
> - Score calibration: what does "healthy" look like for a 5-person volunteer org vs. a $2M nonprofit?
> - Do we want a public health score or keep it internal/for funders only?
> - Instagram data access without page-owner tokens — viable via scraping?

## Links

- [[specs/architecture]] — Full system architecture
- [[specs/airtable-schema]] — Airtable table designs
- [[specs/health-score-model]] — Scoring model detail
- [[notes/api-research]] — API access notes and constraints
