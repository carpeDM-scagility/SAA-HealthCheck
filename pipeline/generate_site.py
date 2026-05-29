"""
SAA Org Health Tracker — Static Site Data Generator
Reads organizations and health scores from Supabase and writes JSON files for GitHub Pages.

Output:
  docs/data/orgs.json    — public org records (no health data)
  docs/data/meta.json    — filter options (states, services, communities)
  docs/data/scores.json  — health scores per org (private dashboard data)

Usage:
  python generate_site.py
  python generate_site.py --output-dir ../docs/data

Env vars: SUPABASE_URL, SUPABASE_KEY
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Public fields only — no EIN, health scores, budget, pipeline internals,
# or contact info (email/website/social are fetched on-demand via anon key
# to prevent bulk scraping of the contact database)
PUBLIC_FIELDS = ",".join([
    "id",
    "name",
    "description",
    "state",
    "service_area",
    "scope_of_service",
    "year_founded",
    "has_membership",
    "num_members",
    "services",
    "communities_served",
    "primary_contact",
])


def fetch_all_orgs(sb_url: str, sb_key: str) -> list[dict]:
    """Fetch all org records from Supabase with pagination."""
    base = sb_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Accept":        "application/json",
    }

    orgs = []
    limit = 1000
    offset = 0

    while True:
        resp = requests.get(
            f"{base}/organizations",
            headers=headers,
            params={
                "select": PUBLIC_FIELDS,
                "order":  "name.asc",
                "limit":  limit,
                "offset": offset,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        orgs.extend(batch)
        log.info(f"  Fetched {len(orgs)} orgs so far...")
        if len(batch) < limit:
            break
        offset += limit

    return orgs


def clean_org(org: dict) -> dict:
    """Normalize an org record for public consumption."""
    # Ensure arrays are always lists, never None
    org["services"]          = org.get("services") or []
    org["communities_served"] = org.get("communities_served") or []

    # Strip whitespace from text fields
    for field in ("name", "description", "service_area", "scope_of_service", "primary_contact"):
        if org.get(field):
            org[field] = org[field].strip()

    # Remove empty string fields to keep JSON lean
    return {k: v for k, v in org.items() if v is not None and v != "" and v != []}


def build_meta(orgs: list[dict]) -> dict:
    """Build filter metadata — unique sorted values for each filter dimension."""
    states       = sorted({o["state"] for o in orgs if o.get("state")})
    services     = sorted({s for o in orgs for s in (o.get("services") or []) if s})
    communities  = sorted({c for o in orgs for c in (o.get("communities_served") or []) if c})
    scopes       = sorted({o["scope_of_service"] for o in orgs if o.get("scope_of_service")})

    return {
        "total":             len(orgs),
        "states":            states,
        "services":          services,
        "communities":       communities,
        "scopes":            scopes,
    }


def fetch_scores(sb_url: str, sb_key: str) -> list[dict]:
    """
    Fetch health scores joined with org name/state, grouped by org.
    Returns one record per org with latest scores + up to 4 historical quarters.
    """
    base = sb_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Accept":        "application/json",
    }

    # Fetch all health score rows, newest first, with org details embedded
    resp = requests.get(
        f"{base}/health_scores",
        headers=headers,
        params={
            "select": "organization_id,scored_on,total_score,health_tier,"
                      "presence_score,activity_score,reach_score,financial_score,"
                      "qoq_change,trend,notes,"
                      "organizations(name,state,scope_of_service)",
            "order":  "scored_on.desc",
            "limit":  5000,
        },
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()

    # Also fetch org-level summary (health_score, health_tier, last_scored)
    org_resp = requests.get(
        f"{base}/organizations",
        headers=headers,
        params={
            "select": "id,name,state,scope_of_service,health_score,health_tier,last_scored",
            "order":  "name.asc",
            "limit":  2000,
        },
        timeout=30,
    )
    org_resp.raise_for_status()
    org_map = {o["id"]: o for o in org_resp.json()}

    # Group score rows by org
    by_org: dict[str, list] = {}
    for row in rows:
        oid = row["organization_id"]
        if oid not in by_org:
            by_org[oid] = []
        by_org[oid].append(row)

    # Build output: one record per org, history array (max 4 quarters)
    output = []
    for oid, score_rows in by_org.items():
        org_info = org_map.get(oid, {})
        linked   = score_rows[0].get("organizations") or {}
        latest   = score_rows[0]

        history = []
        for r in score_rows[:4]:
            history.append({
                "scored_on":       r.get("scored_on"),
                "total_score":     r.get("total_score"),
                "health_tier":     r.get("health_tier"),
                "presence_score":  r.get("presence_score"),
                "activity_score":  r.get("activity_score"),
                "reach_score":     r.get("reach_score"),
                "financial_score": r.get("financial_score"),
                "qoq_change":      r.get("qoq_change"),
                "trend":           r.get("trend"),
            })

        output.append({
            "id":              oid,
            "name":            linked.get("name") or org_info.get("name", ""),
            "state":           linked.get("state") or org_info.get("state", ""),
            "scope":           linked.get("scope_of_service") or org_info.get("scope_of_service", ""),
            "health_score":    org_info.get("health_score"),
            "health_tier":     org_info.get("health_tier"),
            "last_scored":     org_info.get("last_scored"),
            "presence_score":  latest.get("presence_score"),
            "activity_score":  latest.get("activity_score"),
            "reach_score":     latest.get("reach_score"),
            "financial_score": latest.get("financial_score"),
            "qoq_change":      latest.get("qoq_change"),
            "trend":           latest.get("trend"),
            "history":         history,
        })

    # Add orgs with no scores yet
    scored_ids = set(by_org.keys())
    for oid, org in org_map.items():
        if oid not in scored_ids:
            output.append({
                "id":           oid,
                "name":         org.get("name", ""),
                "state":        org.get("state", ""),
                "scope":        org.get("scope_of_service", ""),
                "health_score": org.get("health_score"),
                "health_tier":  org.get("health_tier"),
                "last_scored":  org.get("last_scored"),
                "history":      [],
            })

    # Sort by health_score desc (nulls last), then name
    output.sort(key=lambda o: (-(o["health_score"] or -1), o["name"].lower()))
    return output


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info(f"  Wrote {path} ({path.stat().st_size:,} bytes)")


def run(output_dir: str = "../docs/data") -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sb_url      = os.environ.get("SUPABASE_URL", "")
    sb_key      = os.environ.get("SUPABASE_KEY", "")
    sb_anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not sb_url or not sb_key:
        log.error("Set SUPABASE_URL and SUPABASE_KEY env vars.")
        sys.exit(1)

    out = Path(output_dir)

    log.info("Fetching orgs from Supabase...")
    raw_orgs = fetch_all_orgs(sb_url, sb_key)
    log.info(f"  {len(raw_orgs)} orgs fetched")

    orgs = [clean_org(o) for o in raw_orgs]
    meta = build_meta(orgs)

    log.info("Fetching health scores from Supabase...")
    scores = fetch_scores(sb_url, sb_key)
    log.info(f"  {len(scores)} org score records built")

    log.info("Writing output files...")
    write_json(out / "orgs.json", orgs)
    write_json(out / "meta.json", meta)
    write_json(out / "scores.json", scores)
    write_json(out / "config.json", {
        "supabase_url":     sb_url,
        "supabase_anon_key": sb_anon_key,
    })

    scored = sum(1 for s in scores if s.get("health_score") is not None)
    log.info(
        f"\nDone. {meta['total']} orgs | "
        f"{len(meta['states'])} states | "
        f"{len(meta['services'])} service types | "
        f"{len(meta['communities'])} community tags | "
        f"{scored} orgs scored"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="../docs/data")
    args = parser.parse_args()
    run(output_dir=args.output_dir)
