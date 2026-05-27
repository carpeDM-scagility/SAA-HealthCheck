"""
SAA Org Health Tracker — Financial Fetcher
Pulls IRS Form 990 data from the ProPublica Nonprofit Explorer API.
Matches orgs by EIN (stored in Airtable) and stores annual financials.
Skips orgs where this tax year has already been fetched.
"""

from __future__ import annotations
import logging
import time
from datetime import date
from typing import Any

import requests

from supabase_client import DbClient as AirtableClient
from config import (
    ORG_NAME, ORG_EIN,
    FIN_TAX_YEAR, FIN_ORGANIZATION, FIN_TOTAL_REVENUE, FIN_TOTAL_EXPENSES,
    FIN_PROGRAM_EXP, FIN_NET_ASSETS, FIN_PROGRAM_RATIO, FIN_REVENUE_YOY,
    FIN_NUM_EMPLOYEES, FIN_FILING_DATE, FIN_EIN_VERIFIED,
    HTTP_TIMEOUT,
)

log = logging.getLogger(__name__)

PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"


# ─────────────────────────────────────────────────────────────
# ProPublica API helpers
# ─────────────────────────────────────────────────────────────

def clean_ein(ein: str) -> str:
    """Normalize EIN to digits only."""
    return re.sub(r"[^0-9]", "", ein) if ein else ""


def fetch_org_by_ein(ein: str) -> dict | None:
    """
    Fetch full org data including all 990 filings from ProPublica.
    Returns the API response dict or None on failure.
    """
    ein_clean = clean_ein(ein)
    if not ein_clean or len(ein_clean) != 9:
        log.warning(f"Invalid EIN: {ein!r}")
        return None

    url = f"{PROPUBLICA_BASE}/organizations/{ein_clean}.json"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code == 404:
            log.warning(f"EIN {ein_clean} not found in ProPublica")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        log.error(f"ProPublica API error for EIN {ein_clean}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching EIN {ein_clean}: {e}")
        return None


def search_by_name(org_name: str, state: str | None = None) -> list[dict]:
    """
    Search ProPublica by org name. Returns list of candidate matches.
    Useful for EIN discovery when EIN isn't in Airtable.
    """
    params = {"q": org_name}
    if state:
        params["state[id]"] = state
    try:
        resp = requests.get(
            f"{PROPUBLICA_BASE}/search.json",
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("organizations", [])
    except Exception as e:
        log.error(f"ProPublica search failed for '{org_name}': {e}")
        return []


def extract_filings(pp_data: dict) -> list[dict]:
    """
    Extract structured annual filing records from a ProPublica org response.
    Returns list sorted by tax year descending.
    """
    filings = []

    # ProPublica returns both filings_with_data and filings_without_data
    for filing in pp_data.get("filings_with_data", []):
        record = parse_filing(filing)
        if record:
            filings.append(record)

    return sorted(filings, key=lambda r: r["tax_year"], reverse=True)


def parse_filing(filing: dict) -> dict | None:
    """Parse a single ProPublica filing into our schema."""
    try:
        tax_year = int(filing.get("tax_prd_yr") or filing.get("taxyear") or 0)
        if not tax_year:
            return None

        total_revenue = _to_int(filing.get("totrevenue"))
        total_expenses = _to_int(filing.get("totfuncexpns"))
        program_expenses = _to_int(filing.get("progsvceexpns"))
        net_assets = _to_int(filing.get("totassetsend", 0)) - _to_int(filing.get("totliabend", 0))

        # Program expense ratio
        program_ratio = None
        if total_expenses and program_expenses is not None:
            program_ratio = round(program_expenses / total_expenses, 4)

        # Filing date
        filing_date = None
        if filing.get("sub_date"):
            try:
                # ProPublica sub_date is MM/DD/YYYY
                from datetime import datetime
                filing_date = datetime.strptime(filing["sub_date"], "%m/%d/%Y").date().isoformat()
            except Exception:
                pass

        return {
            "tax_year": tax_year,
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "program_expenses": program_expenses,
            "net_assets": net_assets,
            "program_ratio": program_ratio,
            "num_employees": _to_int(filing.get("noemployees")),
            "filing_date": filing_date,
        }
    except Exception as e:
        log.warning(f"Failed to parse filing: {e}")
        return None


def compute_yoy_change(filings: list[dict]) -> list[dict]:
    """Add revenue_yoy_change to each filing based on prior year."""
    for i, filing in enumerate(filings):
        if i + 1 < len(filings):
            prev = filings[i + 1]
            curr_rev = filing.get("total_revenue")
            prev_rev = prev.get("total_revenue")
            if curr_rev is not None and prev_rev and prev_rev != 0:
                filing["revenue_yoy_change"] = round((curr_rev - prev_rev) / prev_rev, 4)
            else:
                filing["revenue_yoy_change"] = None
        else:
            filing["revenue_yoy_change"] = None
    return filings


def _to_int(val: Any) -> int | None:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────
# Airtable field builder
# ─────────────────────────────────────────────────────────────

def filing_to_airtable_fields(filing: dict, org_record_id: str) -> dict:
    fields = {
        FIN_TAX_YEAR:     filing["tax_year"],
        FIN_ORGANIZATION: [org_record_id],
        FIN_EIN_VERIFIED: True,
    }
    if filing.get("total_revenue") is not None:
        fields[FIN_TOTAL_REVENUE] = filing["total_revenue"]
    if filing.get("total_expenses") is not None:
        fields[FIN_TOTAL_EXPENSES] = filing["total_expenses"]
    if filing.get("program_expenses") is not None:
        fields[FIN_PROGRAM_EXP] = filing["program_expenses"]
    if filing.get("net_assets") is not None:
        fields[FIN_NET_ASSETS] = filing["net_assets"]
    if filing.get("program_ratio") is not None:
        fields[FIN_PROGRAM_RATIO] = filing["program_ratio"]
    if filing.get("revenue_yoy_change") is not None:
        fields[FIN_REVENUE_YOY] = filing["revenue_yoy_change"]
    if filing.get("num_employees") is not None:
        fields[FIN_NUM_EMPLOYEES] = filing["num_employees"]
    if filing.get("filing_date"):
        fields[FIN_FILING_DATE] = filing["filing_date"]
    return fields


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False, years_back: int = 3) -> dict:
    """
    Fetch 990 data for all orgs with EINs.
    Only stores the most recent `years_back` filings per org.
    Skips tax years already stored in Airtable.

    Args:
        dry_run: Print results without writing to Airtable.
        years_back: Number of annual filings to store per org.
    """
    import re  # needed for clean_ein
    globals()["re"] = re  # make available in module scope

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AirtableClient()

    orgs = client.get_orgs_with_ein()
    log.info(f"Fetching 990 data for {len(orgs)} orgs with EINs...")

    summary = {
        "total": len(orgs), "fetched": 0, "skipped": 0,
        "not_found": 0, "filings_written": 0,
    }

    for i, org in enumerate(orgs, 1):
        org_name = org.get(ORG_NAME, "?")
        ein = org.get(ORG_EIN, "").strip()
        org_id = org["_id"]
        log.info(f"[{i}/{len(orgs)}] {org_name} | EIN: {ein}")

        # Check which tax years we already have
        existing = client.get_financial_for_org(org_id)
        existing_years = {r.get(FIN_TAX_YEAR) for r in existing}

        # Fetch from ProPublica
        pp_data = fetch_org_by_ein(ein)
        if not pp_data:
            summary["not_found"] += 1
            continue

        filings = extract_filings(pp_data)
        filings = compute_yoy_change(filings)
        filings = filings[:years_back]  # Only most recent N years

        summary["fetched"] += 1
        new_filings = [f for f in filings if f["tax_year"] not in existing_years]

        if not new_filings:
            log.info(f"  All {years_back} years already stored — skipping")
            summary["skipped"] += 1
            continue

        log.info(f"  Found {len(filings)} filings, writing {len(new_filings)} new")

        for filing in new_filings:
            if dry_run:
                print(f"  Year {filing['tax_year']}: revenue=${filing.get('total_revenue'):,} "
                      f"program_ratio={filing.get('program_ratio'):.1%}")
            else:
                fields = filing_to_airtable_fields(filing, org_id)
                try:
                    client.write_financial_metric(fields)
                    summary["filings_written"] += 1
                except Exception as e:
                    log.error(f"  Failed to write filing {filing['tax_year']} for {org_name}: {e}")

        # Be respectful to ProPublica (no auth required, so rate limit gently)
        time.sleep(0.5)

    log.info(
        f"Done. Fetched: {summary['fetched']}, Not found: {summary['not_found']}, "
        f"Filings written: {summary['filings_written']}"
    )
    return summary


if __name__ == "__main__":
    import re
    import sys
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
