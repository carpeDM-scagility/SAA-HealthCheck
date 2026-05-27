"""
SAA Org Health Tracker — EIN Enricher
Searches ProPublica by org name + state to find EINs for orgs
that don't have one in Airtable yet.

Confidence tiers:
  HIGH (≥0.85)   — auto-writes EIN to Airtable
  MEDIUM (≥0.55) — saved to review CSV for manual confirmation
  LOW  (<0.55)   — skipped silently (no useful match found)

Usage:
  python ein_enricher.py --dry-run    # show findings, write nothing
  python ein_enricher.py              # write high-confidence, save review CSV
"""

from __future__ import annotations

import csv
import logging
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

from airtable_client import AirtableClient
from config import ORG_NAME, ORG_EIN, ORG_STATE, HTTP_TIMEOUT

log = logging.getLogger(__name__)

PROPUBLICA_SEARCH = "https://projects.propublica.org/nonprofits/api/v2/search.json"

# Confidence thresholds
HIGH_CONFIDENCE   = 0.85
MEDIUM_CONFIDENCE = 0.55

# Words to strip before comparing names
STRIP_WORDS = {
    "the", "a", "an", "of", "and", "for", "in", "at", "to",
    "inc", "incorporated", "llc", "ltd", "corp", "corporation",
    "association", "assn", "assoc",
    "foundation", "fdn",
    "organization", "org",
    "nonprofit", "non-profit",
    "chapter",
}


# ─────────────────────────────────────────────────────────────
# Name similarity
# ─────────────────────────────────────────────────────────────

def normalize(name: str) -> set[str]:
    """Lowercase, strip punctuation, remove filler words → set of tokens."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    tokens = name.split()
    return {t for t in tokens if t not in STRIP_WORDS and len(t) > 1}


def similarity(our_name: str, their_name: str) -> float:
    """
    Jaccard-style overlap between the meaningful word sets of two names.
    Returns 0.0–1.0.
    """
    a = normalize(our_name)
    b = normalize(their_name)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


# ─────────────────────────────────────────────────────────────
# ProPublica search
# ─────────────────────────────────────────────────────────────

def search_propublica(org_name: str, state: str | None) -> list[dict]:
    """
    Search ProPublica for org_name, optionally scoped by state code.
    Returns raw list of org dicts from the API.
    """
    params: dict = {"q": org_name}
    if state and len(state.strip()) == 2:
        params["state[id]"] = state.strip().upper()

    try:
        resp = requests.get(PROPUBLICA_SEARCH, params=params, timeout=HTTP_TIMEOUT)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("organizations", [])
    except Exception as e:
        log.warning(f"ProPublica search failed for '{org_name}': {e}")
        return []


def best_match(our_name: str, candidates: list[dict]) -> tuple[dict | None, float]:
    """
    Find the highest-similarity candidate.
    Returns (best_candidate_dict, score) or (None, 0.0).
    """
    best: dict | None = None
    best_score = 0.0

    for c in candidates:
        their_name = c.get("name", "")
        score = similarity(our_name, their_name)
        if score > best_score:
            best_score = score
            best = c

    return best, best_score


def format_ein(raw_ein: str | int | None) -> str | None:
    """Normalize EIN to XX-XXXXXXX format."""
    if raw_ein is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw_ein))
    if len(digits) == 9:
        return f"{digits[:2]}-{digits[2:]}"
    return None


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = AirtableClient()
    orgs = client.get_orgs_without_ein()
    log.info(f"Found {len(orgs)} orgs without EIN — searching ProPublica...")

    summary = {
        "total": len(orgs),
        "high": 0,      # auto-written
        "medium": 0,    # flagged for review
        "low": 0,       # no good match
        "error": 0,
    }

    review_rows: list[dict] = []

    for i, org in enumerate(orgs, 1):
        org_name = org.get(ORG_NAME, "").strip()
        org_state = org.get(ORG_STATE, "").strip()
        org_id = org["_id"]

        if not org_name:
            log.warning(f"[{i}/{len(orgs)}] Skipping record with no name")
            summary["error"] += 1
            continue

        log.info(f"[{i}/{len(orgs)}] {org_name} ({org_state or '??'})")

        candidates = search_propublica(org_name, org_state)

        if not candidates:
            log.info(f"  No results from ProPublica")
            summary["low"] += 1
            time.sleep(0.4)
            continue

        match, score = best_match(org_name, candidates)
        ein = format_ein(match.get("ein")) if match else None
        match_name = match.get("name", "") if match else ""
        match_city = match.get("city", "") if match else ""
        match_state = match.get("state", "") if match else ""

        if score >= HIGH_CONFIDENCE and ein:
            summary["high"] += 1
            log.info(
                f"  ✓ HIGH ({score:.2f}) → {match_name} | EIN: {ein}"
            )
            if dry_run:
                print(
                    f"  WOULD WRITE: {org_name} → EIN {ein}  "
                    f"(matched: '{match_name}', score={score:.2f})"
                )
            else:
                try:
                    client.update_org_ein(org_id, ein)
                    log.info(f"  Written.")
                except Exception as e:
                    log.error(f"  Failed to write EIN: {e}")
                    summary["error"] += 1

        elif score >= MEDIUM_CONFIDENCE and ein:
            summary["medium"] += 1
            log.info(
                f"  ~ MEDIUM ({score:.2f}) → {match_name} | {match_city}, {match_state}"
            )
            review_rows.append({
                "airtable_id":  org_id,
                "our_name":     org_name,
                "our_state":    org_state,
                "match_name":   match_name,
                "match_city":   match_city,
                "match_state":  match_state,
                "ein":          ein,
                "score":        f"{score:.2f}",
            })

        else:
            summary["low"] += 1
            log.info(f"  ✗ LOW ({score:.2f}) — skipped")

        # Be polite to ProPublica (no auth required)
        time.sleep(0.4)

    # Write review CSV
    if review_rows:
        today = date.today().strftime("%Y%m%d")
        csv_path = Path(__file__).parent / f"ein_review_{today}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=review_rows[0].keys())
            writer.writeheader()
            writer.writerows(review_rows)
        log.info(f"\nReview CSV written: {csv_path}")
        log.info(f"  Open it, check the matches, delete rows you don't want,")
        log.info(f"  then run: python ein_enricher.py --apply-review {csv_path}")
    else:
        log.info("No medium-confidence matches to review.")

    log.info(
        f"\nDone. High (auto): {summary['high']}  "
        f"Medium (review): {summary['medium']}  "
        f"Low/none: {summary['low']}  "
        f"Errors: {summary['error']}"
    )
    return summary


def apply_review(csv_path: str) -> None:
    """
    Apply EINs from a manually-verified review CSV.
    Rows in the CSV are treated as confirmed — just write them all.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AirtableClient()
    path = Path(csv_path)

    if not path.exists():
        log.error(f"File not found: {csv_path}")
        return

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    log.info(f"Applying {len(rows)} confirmed EINs from {path.name}...")
    written = 0

    for row in rows:
        org_id = row.get("airtable_id", "").strip()
        ein = row.get("ein", "").strip()
        name = row.get("our_name", "")

        if not org_id or not ein:
            log.warning(f"Skipping incomplete row: {row}")
            continue

        try:
            client.update_org_ein(org_id, ein)
            log.info(f"  ✓ {name} → {ein}")
            written += 1
        except Exception as e:
            log.error(f"  Failed for {name}: {e}")

        time.sleep(0.2)

    log.info(f"Done. {written}/{len(rows)} EINs written.")


if __name__ == "__main__":
    if "--apply-review" in sys.argv:
        idx = sys.argv.index("--apply-review")
        if idx + 1 < len(sys.argv):
            apply_review(sys.argv[idx + 1])
        else:
            print("Usage: python ein_enricher.py --apply-review <path/to/csv>")
    else:
        dry = "--dry-run" in sys.argv
        run(dry_run=dry)
