"""
SAA Org Health Tracker — One-Time Airtable → Supabase Migration
Uses plain requests for both Airtable and Supabase — no supabase package needed.

Usage:
  python migrate_to_supabase.py --dry-run   # count records, write nothing
  python migrate_to_supabase.py             # run the full migration
"""

from __future__ import annotations

import logging
import os
import sys
import time

import requests
from pyairtable import Api

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Airtable field ID → Supabase column mappings (migration only)
# ─────────────────────────────────────────────────────────────

AT_BASE_ID = "app6ACspUBzaoNnAQ"

AT_ORG_FIELDS = {
    "fldq57nc4EWYzPHWJ": "name",
    "fldmSdoEQJWeiA21p": "website_url",
    "fldJmri85xmMUD9IH": "facebook_url",
    "flduJOtgYnFtOkUxo": "instagram_url",
    "fldfNnzXXgJwDsvPu": "email",
    "fldO8m4pd5pi0S5cQ": "ein",
    "fldhcuHfhKzXdvSRo": "state",
    "fld0N0AdEmxYDlAMX": "scope",
    "fld3vKoXPcKYtU7st": "health_score",
    "fldKXHE9igr9m3fCs": "health_tier",
    "fldWe3qFg6GRlFgfQ": "last_scored",
}

AT_SOCIAL_FIELDS = {
    "fldscJ4YW6BI2stye": "collected_on",
    "fld2PNRo7gldvuCTg": "platform",
    "fld4vx6rdIiGxHYPz": "is_active",
    "fld72IXEWj799yEnu": "followers",
    "fldnPZ04LuD3eD7Vp": "posts_30d",
    "fldoJfodMXGytagU2": "posts_90d",
    "fldDoD1q5FFvcKDBv": "last_post_date",
    "fldE0ITj9bsJrzI1O": "engagement_rate",
    "fld2XuLBlj5SHPji7": "avg_likes",
    "fldpj45T2LSAUwpV9": "avg_comments",
    "fldUGCnKQJDQQsr3M": "follower_growth",
    "fldIB6uQPcYAZURRZ": "raw_data",
}

AT_FINANCIAL_FIELDS = {
    "fldF1ILKkl3toJc5d": "tax_year",
    "fld7tQ6ZXfr2JFIo4": "total_revenue",
    "fld1upIl1Uk0SZ5Tc": "total_expenses",
    "fldr8DyYBFwlGHGXD": "program_expenses",
    "fldQr4kbzdqyXZn7O": "net_assets",
    "fldDWA77ouf5tH7Z9": "program_ratio",
    "fldaYWUpzbV7CvpLz": "revenue_yoy",
    "fldxYpijCUZC8BwjA": "num_employees",
    "fldaPqQErE43E7sCZ": "filing_date",
    "fldB2q7QYv8blPjiY": "ein_verified",
}

AT_HEALTH_FIELDS = {
    "fldfRse6kswEikoVr": "scored_on",
    "fldjy6gQcaeG8YM6n": "total_score",
    "fldFpy61aH2F3EJlB": "health_tier",
    "fldjW6gUeKb6ZuM7k": "presence_score",
    "fld5dgn47kqG9ZdJ9": "activity_score",
    "fldlrDINXmo9Hnn5q": "reach_score",
    "fldJ1AsXpa2mCODOt": "financial_score",
    "fldOS3JaPtjdBFzAx": "qoq_change",
    "fldWnZPmHTkbofVqU": "trend",
    "fldrn8TVE7kcdSdJ8": "notes",
}

AT_SOCIAL_ORG_FIELD    = "fldo1L7eWiqfQfWVK"
AT_FINANCIAL_ORG_FIELD = "fldr9AqgjimCtZ0xQ"
AT_HEALTH_ORG_FIELD    = "fldagIiV0cZWAjyjM"
AT_ORG_NAME_FIELD      = "fldq57nc4EWYzPHWJ"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def translate(fields: dict, mapping: dict) -> dict:
    return {col: fields[at_id] for at_id, col in mapping.items() if at_id in fields and fields[at_id] is not None}


def sb_insert(sb_base: str, sb_headers: dict, table: str, rows: list[dict],
               batch_size: int = 100, on_conflict: str | None = None) -> int:
    if not rows:
        return 0
    # PostgREST requires all rows in a batch to have identical keys.
    all_keys = set()
    for row in rows:
        all_keys.update(row.keys())
    normalized = [{k: row.get(k) for k in all_keys} for row in rows]

    prefer = "resolution=merge-duplicates,return=minimal" if on_conflict else "return=minimal"
    url_params = f"?on_conflict={on_conflict}" if on_conflict else ""

    inserted = 0
    for i in range(0, len(normalized), batch_size):
        batch = normalized[i:i + batch_size]
        resp = requests.post(
            f"{sb_base}/{table}{url_params}",
            headers={**sb_headers, "Prefer": prefer},
            json=batch,
            timeout=30,
        )
        if not resp.ok:
            log.error(f"  Insert failed: {resp.status_code} {resp.text[:200]}")
            resp.raise_for_status()
        inserted += len(batch)
        log.info(f"  {table}: {inserted}/{len(rows)} inserted")
        time.sleep(0.2)
    return inserted


def sb_select(sb_base: str, sb_headers: dict, table: str, params: dict) -> list[dict]:
    resp = requests.get(f"{sb_base}/{table}", headers=sb_headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    at_key = os.environ.get("AIRTABLE_API_KEY", "")
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")

    if not all([at_key, sb_url, sb_key]):
        log.error("Set AIRTABLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY first.")
        sys.exit(1)

    sb_base = sb_url.rstrip("/") + "/rest/v1"
    sb_headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type":  "application/json",
    }

    # Connect to Airtable
    at_api      = Api(at_key, use_field_ids=True)
    at_orgs     = at_api.table(AT_BASE_ID, "tblgKYNjvlQNU9I24")
    at_social   = at_api.table(AT_BASE_ID, "tblSw6F4oZNH99xSF")
    at_financial= at_api.table(AT_BASE_ID, "tblj8lKAPrJl9Xn5A")
    at_health   = at_api.table(AT_BASE_ID, "tblKFO3HpkoOO5HPj")

    # ── Step 1: Organizations ────────────────────────────────
    log.info("Reading organizations from Airtable...")
    at_org_records = at_orgs.all()
    log.info(f"  Found {len(at_org_records)} orgs")

    org_rows = []
    for r in at_org_records:
        row = translate(r["fields"], AT_ORG_FIELDS)
        if row.get("name"):
            org_rows.append(row)

    if dry_run:
        log.info(f"[DRY RUN] Would insert {len(org_rows)} orgs — skipping")
    else:
        sb_insert(sb_base, sb_headers, "organizations", org_rows)

    # ── Build Airtable record ID → Supabase UUID map ─────────
    log.info("Building ID map...")
    sb_orgs = sb_select(sb_base, sb_headers, "organizations", {"select": "id,name"})
    name_to_sb_id = {r["name"]: r["id"] for r in sb_orgs}
    at_id_to_name = {r["id"]: r["fields"].get(AT_ORG_NAME_FIELD, "") for r in at_org_records}
    at_id_to_sb_id = {
        at_id: name_to_sb_id[name]
        for at_id, name in at_id_to_name.items()
        if name in name_to_sb_id
    }
    log.info(f"  Mapped {len(at_id_to_sb_id)}/{len(at_org_records)} orgs to Supabase UUIDs")

    # ── Step 2: Social Metrics ───────────────────────────────
    log.info("Reading social metrics from Airtable...")
    at_social_records = at_social.all()
    log.info(f"  Found {len(at_social_records)} social metric records")

    social_rows = []
    for r in at_social_records:
        org_links = r["fields"].get(AT_SOCIAL_ORG_FIELD, [])
        if not org_links:
            continue
        sb_id = at_id_to_sb_id.get(org_links[0])
        if not sb_id:
            continue
        row = translate(r["fields"], AT_SOCIAL_FIELDS)
        row["organization_id"] = sb_id
        social_rows.append(row)

    log.info(f"  Translated {len(social_rows)} social rows")
    if not dry_run and social_rows:
        sb_insert(sb_base, sb_headers, "social_metrics", social_rows)

    # ── Step 3: Financial Metrics ────────────────────────────
    log.info("Reading financial metrics from Airtable...")
    at_fin_records = at_financial.all()
    log.info(f"  Found {len(at_fin_records)} financial records")

    fin_rows = []
    for r in at_fin_records:
        org_links = r["fields"].get(AT_FINANCIAL_ORG_FIELD, [])
        if not org_links:
            continue
        sb_id = at_id_to_sb_id.get(org_links[0])
        if not sb_id:
            continue
        row = translate(r["fields"], AT_FINANCIAL_FIELDS)
        row["organization_id"] = sb_id
        fin_rows.append(row)

    # Deduplicate on (organization_id, tax_year) — keep last occurrence
    seen_fin = {}
    for row in fin_rows:
        key = (row.get("organization_id"), row.get("tax_year"))
        seen_fin[key] = row
    fin_rows = list(seen_fin.values())
    log.info(f"  Translated {len(fin_rows)} financial rows (after dedup)")
    if not dry_run and fin_rows:
        sb_insert(sb_base, sb_headers, "financial_metrics", fin_rows,
                  on_conflict="organization_id,tax_year")

    # ── Step 4: Health Scores ────────────────────────────────
    log.info("Reading health scores from Airtable...")
    at_health_records = at_health.all()
    log.info(f"  Found {len(at_health_records)} health score records")

    health_rows = []
    for r in at_health_records:
        org_links = r["fields"].get(AT_HEALTH_ORG_FIELD, [])
        if not org_links:
            continue
        sb_id = at_id_to_sb_id.get(org_links[0])
        if not sb_id:
            continue
        row = translate(r["fields"], AT_HEALTH_FIELDS)
        row["organization_id"] = sb_id
        health_rows.append(row)

    log.info(f"  Translated {len(health_rows)} health score rows")
    if not dry_run and health_rows:
        sb_insert(sb_base, sb_headers, "health_scores", health_rows)

    # ── Summary ──────────────────────────────────────────────
    log.info(f"\n=== Migration {'DRY RUN' if dry_run else 'COMPLETE'} ===")
    log.info(f"  Organizations:    {len(org_rows)}")
    log.info(f"  Social Metrics:   {len(social_rows)}")
    log.info(f"  Financial Metrics:{len(fin_rows)}")
    log.info(f"  Health Scores:    {len(health_rows)}")
    if dry_run:
        log.info("\nRun without --dry-run to write to Supabase.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
