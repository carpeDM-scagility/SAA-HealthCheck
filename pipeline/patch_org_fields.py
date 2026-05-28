"""
SAA Org Health Tracker — Patch Organizations with New Fields
Fetches additional org fields from Airtable and updates Supabase records.

New fields added:
  twitter_url, description, year_founded, services (text[]),
  communities_served (text[]), scope_of_service, service_area,
  has_membership, num_members, primary_contact

Usage:
  python patch_org_fields.py --dry-run   # preview, no writes
  python patch_org_fields.py             # write to Supabase

Requires: AIRTABLE_API_KEY, SUPABASE_URL, SUPABASE_KEY env vars
"""

from __future__ import annotations
import logging
import os
import sys
import time

import requests
from pyairtable import Api

log = logging.getLogger(__name__)

AT_BASE_ID = "app6ACspUBzaoNnAQ"

# Airtable field IDs — Organizations table
AT_ORG_NAME         = "fldq57nc4EWYzPHWJ"
AT_TWITTER          = "fld0VkTTNKskkcHTW"
AT_DESCRIPTION      = "flduBDsNx4Y7TobBI"
AT_YEAR_FOUNDED     = "flda9Egjr9ZR132hf"
AT_SERVICES         = "fldB0tmsdCO7Vd0SJ"    # multipleRecordLinks → Services table
AT_COMMUNITIES      = "fldHSt5Q8W8QyS8Kl"    # multipleRecordLinks → Communities Served table
AT_SCOPE            = "fld0N0AdEmxYDlAMX"     # singleSelect
AT_SERVICE_AREA     = "fldeKdyK5Kcjwn0ZA"
AT_MEMBERSHIP       = "fldWUJgD4c5vPnM4p"     # singleSelect (Yes/No)
AT_NUM_MEMBERS      = "fldEDLaJ88xX7OboV"
AT_PRIMARY_CONTACT  = "fldpK2aFdBDQaK5nK"

# Linked table IDs
AT_SERVICES_TABLE        = "tbl1KvBhClxYmygBf"
AT_SERVICES_NAME_FLD     = "flddT7lRn8qxvwiZU"
AT_COMMUNITIES_TABLE     = "tblkPEy5IA4kD8t7a"
AT_COMMUNITIES_NAME_FLD  = "fld42pxRVpaAezsPy"


# ─────────────────────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────────────────────

def sb_patch(sb_base: str, sb_headers: dict, table: str, record_id: str, data: dict) -> bool:
    """PATCH a single Supabase record by its UUID."""
    resp = requests.patch(
        f"{sb_base}/{table}",
        headers={**sb_headers, "Prefer": "return=minimal"},
        params={"id": f"eq.{record_id}"},
        json=data,
        timeout=30,
    )
    if not resp.ok:
        log.error(f"  PATCH failed ({resp.status_code}): {resp.text[:200]}")
    return resp.ok


def sb_get_all_orgs(sb_base: str, sb_headers: dict) -> dict[str, str]:
    """Fetch all orgs from Supabase. Returns {name: id} map."""
    all_rows = []
    limit = 1000
    offset = 0
    while True:
        resp = requests.get(
            f"{sb_base}/organizations",
            headers={**sb_headers, "Range-Unit": "items", "Range": f"{offset}-{offset + limit - 1}"},
            params={"select": "id,name"},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        all_rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return {r["name"]: r["id"] for r in all_rows}


# ─────────────────────────────────────────────────────────────
# Field translation helpers
# ─────────────────────────────────────────────────────────────

def _select_val(val) -> str | None:
    """Extract string from singleSelect field (may be dict or string)."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("name")
    return None


def _resolve_links(record_ids: list, lookup: dict) -> list[str]:
    """Resolve a list of Airtable record IDs to their primary field values."""
    return [lookup[rid] for rid in (record_ids or []) if rid in lookup]


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
        log.error("Missing env vars. Set AIRTABLE_API_KEY, SUPABASE_URL, and SUPABASE_KEY.")
        sys.exit(1)

    sb_base = sb_url.rstrip("/") + "/rest/v1"
    sb_headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type":  "application/json",
    }

    at_api = Api(at_key, use_field_ids=True)

    # ── Build linked table lookups ─────────────────────────────
    log.info("Fetching Services lookup table...")
    services_lookup: dict[str, str] = {
        r["id"]: r["fields"][AT_SERVICES_NAME_FLD]
        for r in at_api.table(AT_BASE_ID, AT_SERVICES_TABLE).all()
        if r["fields"].get(AT_SERVICES_NAME_FLD)
    }
    log.info(f"  {len(services_lookup)} service types loaded")

    log.info("Fetching Communities Served lookup table...")
    communities_lookup: dict[str, str] = {
        r["id"]: r["fields"][AT_COMMUNITIES_NAME_FLD]
        for r in at_api.table(AT_BASE_ID, AT_COMMUNITIES_TABLE).all()
        if r["fields"].get(AT_COMMUNITIES_NAME_FLD)
    }
    log.info(f"  {len(communities_lookup)} community tags loaded")

    # ── Build Supabase name → id map ───────────────────────────
    log.info("Loading Supabase org IDs...")
    name_to_sb_id = sb_get_all_orgs(sb_base, sb_headers)
    log.info(f"  {len(name_to_sb_id)} orgs in Supabase")

    # ── Fetch all org records from Airtable ────────────────────
    log.info("Fetching org records from Airtable...")
    org_records = at_api.table(AT_BASE_ID, "tblgKYNjvlQNU9I24").all()
    log.info(f"  {len(org_records)} org records fetched")

    updated = 0
    no_match = 0
    no_data = 0
    errors = 0

    for r in org_records:
        fields = r["fields"]
        name = (fields.get(AT_ORG_NAME) or "").replace("\n", " ").strip()

        # Look up Supabase ID
        sb_id = name_to_sb_id.get(name)
        if not sb_id:
            # Try original (with newlines) as fallback
            sb_id = name_to_sb_id.get(fields.get(AT_ORG_NAME, ""))
        if not sb_id:
            log.warning(f"  No Supabase match: {name!r}")
            no_match += 1
            continue

        # ── Build patch payload ──────────────────────────────
        patch: dict = {}

        if fields.get(AT_TWITTER):
            patch["twitter_url"] = fields[AT_TWITTER]

        if fields.get(AT_DESCRIPTION):
            patch["description"] = fields[AT_DESCRIPTION].strip()

        if fields.get(AT_YEAR_FOUNDED) is not None:
            try:
                patch["year_founded"] = int(fields[AT_YEAR_FOUNDED])
            except (TypeError, ValueError):
                pass

        if fields.get(AT_SERVICE_AREA):
            patch["service_area"] = fields[AT_SERVICE_AREA].strip()

        if fields.get(AT_PRIMARY_CONTACT):
            patch["primary_contact"] = fields[AT_PRIMARY_CONTACT].strip()

        if fields.get(AT_NUM_MEMBERS) is not None:
            try:
                patch["num_members"] = int(fields[AT_NUM_MEMBERS])
            except (TypeError, ValueError):
                pass

        scope = _select_val(fields.get(AT_SCOPE))
        if scope:
            patch["scope_of_service"] = scope

        membership_val = _select_val(fields.get(AT_MEMBERSHIP))
        if membership_val:
            patch["has_membership"] = membership_val.lower() == "yes"

        services = _resolve_links(fields.get(AT_SERVICES, []), services_lookup)
        if services:
            patch["services"] = services

        communities = _resolve_links(fields.get(AT_COMMUNITIES, []), communities_lookup)
        if communities:
            patch["communities_served"] = communities

        if not patch:
            no_data += 1
            continue

        # ── Write or preview ─────────────────────────────────
        if dry_run:
            log.info(f"  [DRY] {name}")
            for k, v in patch.items():
                log.info(f"        {k}: {v}")
            updated += 1
        else:
            ok = sb_patch(sb_base, sb_headers, "organizations", sb_id, patch)
            if ok:
                updated += 1
            else:
                errors += 1

        time.sleep(0.05)  # gentle on Supabase rate limits

    log.info(
        f"\n=== {'DRY RUN' if dry_run else 'COMPLETE'} ===\n"
        f"  Updated:   {updated}\n"
        f"  No match:  {no_match}\n"
        f"  No data:   {no_data}\n"
        f"  Errors:    {errors}"
    )


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
