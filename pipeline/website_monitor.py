"""
SAA Org Health Tracker — Website Monitor
Checks liveness, SSL, response time, freshness, and contact signals
for every org that has a website URL. Writes results to Social Metrics table.
"""

from __future__ import annotations
import logging
import re
import ssl
import socket
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from supabase_client import DbClient as AirtableClient
from config import (
    ORG_NAME, ORG_WEBSITE,
    SM_COLLECTION_DATE, SM_ORGANIZATION, SM_PLATFORM,
    SM_IS_ACTIVE, SM_LAST_POST_DATE, SM_RAW_DATA,
    HTTP_TIMEOUT,
)

log = logging.getLogger(__name__)

# Patterns that suggest a contact page or info exists
CONTACT_PATTERNS = [
    r'href=["\'][^"\']*contact[^"\']*["\']',
    r'href=["\'][^"\']*about[^"\']*["\']',
    r'mailto:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # US phone
]

# These indicate an org is using Facebook as their "website" — flag but don't skip
FACEBOOK_AS_WEBSITE_PATTERN = re.compile(r'facebook\.com', re.IGNORECASE)


def check_ssl(url: str) -> bool:
    """True if the URL uses HTTPS and the cert is valid."""
    if not url.startswith("https://"):
        return False
    try:
        parsed = urlparse(url)
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.socket(), server_hostname=parsed.hostname
        ) as s:
            s.settimeout(HTTP_TIMEOUT)
            s.connect((parsed.hostname, 443))
        return True
    except Exception:
        return False


def parse_last_modified(response: requests.Response) -> str | None:
    """Extract last-modified date from headers, return ISO date string or None."""
    lm = response.headers.get("Last-Modified")
    if not lm:
        return None
    try:
        return parsedate_to_datetime(lm).date().isoformat()
    except Exception:
        return None


def detect_contact_signals(html: str) -> bool:
    """Return True if the page appears to have contact information."""
    for pattern in CONTACT_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            return True
    return False


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme."""
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def check_website(org: dict) -> dict:
    """
    Run all health checks on a single org's website.
    Returns a dict of results suitable for writing to Social Metrics.
    """
    raw_url = org.get(ORG_WEBSITE, "").strip()
    org_name = org.get(ORG_NAME, "unknown")
    org_id = org["_id"]

    result = {
        "org_id": org_id,
        "org_name": org_name,
        "url": raw_url,
        "is_facebook_url": bool(FACEBOOK_AS_WEBSITE_PATTERN.search(raw_url)),
        "is_live": False,
        "status_code": None,
        "ssl_valid": False,
        "response_ms": None,
        "last_modified": None,
        "has_contact": False,
        "error": None,
    }

    if not raw_url:
        result["error"] = "no_url"
        return result

    if result["is_facebook_url"]:
        # Count as "active presence" but not a real website — flag it
        result["is_live"] = True
        result["error"] = "facebook_as_website"
        log.warning(f"[{org_name}] Website field contains Facebook URL: {raw_url}")
        return result

    url = normalize_url(raw_url)
    result["ssl_valid"] = url.startswith("https://") and check_ssl(url)

    try:
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "SAACommunityHealthBot/1.0 (+https://github.com/your-org)"},
        )
        result["status_code"] = resp.status_code
        result["is_live"] = resp.status_code < 400
        result["response_ms"] = int(resp.elapsed.total_seconds() * 1000)
        result["last_modified"] = parse_last_modified(resp)

        if result["is_live"] and len(resp.text) > 200:
            result["has_contact"] = detect_contact_signals(resp.text[:50_000])

    except requests.exceptions.SSLError as e:
        result["ssl_valid"] = False
        result["error"] = f"ssl_error: {e}"
        # Try http fallback
        try:
            http_url = url.replace("https://", "http://")
            resp = requests.get(http_url, timeout=HTTP_TIMEOUT, allow_redirects=True)
            result["status_code"] = resp.status_code
            result["is_live"] = resp.status_code < 400
        except Exception:
            pass
    except requests.exceptions.Timeout:
        result["error"] = "timeout"
    except requests.exceptions.ConnectionError:
        result["error"] = "connection_error"
    except Exception as e:
        result["error"] = str(e)

    return result


def result_to_airtable_fields(result: dict, org_record_id: str) -> dict:
    """Convert a check result into Airtable Social Metrics fields."""
    raw = {k: v for k, v in result.items() if v is not None}
    fields = {
        SM_COLLECTION_DATE: date.today().isoformat(),
        SM_ORGANIZATION:    [org_record_id],
        SM_PLATFORM:        "Website",
        SM_IS_ACTIVE:       result["is_live"],
        SM_RAW_DATA:        str(raw),
    }
    if result.get("last_modified"):
        fields[SM_LAST_POST_DATE] = result["last_modified"]
    return fields


def run(dry_run: bool = False) -> dict:
    """
    Main entry point. Checks all orgs with websites and writes results.

    Args:
        dry_run: If True, print results without writing to Airtable.

    Returns:
        Summary dict with counts.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AirtableClient()

    orgs = client.get_orgs_with_websites()
    log.info(f"Checking websites for {len(orgs)} orgs...")

    summary = {"total": len(orgs), "live": 0, "dead": 0, "error": 0, "written": 0}

    for i, org in enumerate(orgs, 1):
        org_name = org.get(ORG_NAME, "?")
        log.info(f"[{i}/{len(orgs)}] {org_name}")

        result = check_website(org)

        if result["is_live"]:
            summary["live"] += 1
        elif result["error"]:
            summary["error"] += 1
        else:
            summary["dead"] += 1

        if dry_run:
            status = "✓ LIVE" if result["is_live"] else f"✗ {result.get('error', 'dead')}"
            print(f"  {status:20s} | ssl:{result['ssl_valid']} | {result['url'][:60]}")
        else:
            fields = result_to_airtable_fields(result, org["_id"])
            try:
                client.write_social_metric(fields)
                summary["written"] += 1
            except Exception as e:
                log.error(f"  Failed to write metric for {org_name}: {e}")

    log.info(
        f"Done. Live: {summary['live']}, Dead: {summary['dead']}, "
        f"Error: {summary['error']}, Written: {summary['written']}"
    )
    return summary


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
