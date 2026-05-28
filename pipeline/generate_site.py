"""
SAA Org Health Tracker — Static Site Data Generator
Reads organizations from Supabase and writes public JSON files for GitHub Pages.
Excludes sensitive fields (EIN, health scores, budget).

Output:
  docs/data/orgs.json   — array of public org records (sorted by name)
  docs/data/meta.json   — unique filter values (states, services, communities)

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

# Public fields only — no EIN, health scores, budget, or pipeline internals
PUBLIC_FIELDS = ",".join([
    "id",
    "name",
    "description",
    "website_url",
    "email",
    "twitter_url",
    "facebook_url",
    "instagram_url",
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


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info(f"  Wrote {path} ({path.stat().st_size:,} bytes)")


def run(output_dir: str = "../docs/data") -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        log.error("Set SUPABASE_URL and SUPABASE_KEY env vars.")
        sys.exit(1)

    out = Path(output_dir)

    log.info("Fetching orgs from Supabase...")
    raw_orgs = fetch_all_orgs(sb_url, sb_key)
    log.info(f"  {len(raw_orgs)} orgs fetched")

    orgs = [clean_org(o) for o in raw_orgs]
    meta = build_meta(orgs)

    log.info("Writing output files...")
    write_json(out / "orgs.json", orgs)
    write_json(out / "meta.json", meta)

    log.info(
        f"\nDone. {meta['total']} orgs | "
        f"{len(meta['states'])} states | "
        f"{len(meta['services'])} service types | "
        f"{len(meta['communities'])} community tags"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="../docs/data")
    args = parser.parse_args()
    run(output_dir=args.output_dir)
