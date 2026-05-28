"""
SAA Org Health Tracker — Social Crawler
Collects follower counts, post frequency, and engagement metrics
from Facebook (via Meta Graph API) and Instagram (via Apify).
Writes results to Social Metrics table.
"""

from __future__ import annotations
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from supabase_client import DbClient as AirtableClient
from config import (
    ORG_NAME, ORG_FACEBOOK, ORG_INSTAGRAM,
    SM_COLLECTION_DATE, SM_ORGANIZATION, SM_PLATFORM,
    SM_IS_ACTIVE, SM_FOLLOWERS, SM_POSTS_30D, SM_POSTS_90D,
    SM_LAST_POST_DATE, SM_ENGAGEMENT_RATE, SM_AVG_LIKES,
    SM_AVG_COMMENTS, SM_FOLLOWER_GROWTH, SM_RAW_DATA,
    META_APP_ID, META_APP_SECRET, APIFY_TOKEN, HTTP_TIMEOUT,
)

log = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
APIFY_ACTOR_ID = "apify~instagram-profile-scraper"


# ─────────────────────────────────────────────────────────────
# URL parsing helpers
# ─────────────────────────────────────────────────────────────

def extract_fb_identifier(url: str) -> tuple[str, str]:
    """
    Parse a Facebook URL and return (identifier, type).
    type is one of: 'page', 'group', 'profile_id', 'unknown'

    Examples:
        facebook.com/adhikaar                -> ('adhikaar', 'page')
        facebook.com/groups/138185376966592  -> ('138185376966592', 'group')
        facebook.com/profile.php?id=100054   -> ('100054', 'profile_id')
    """
    if not url:
        return ("", "unknown")
    url = url.strip().rstrip("/")

    # Group URL
    m = re.search(r'facebook\.com/groups/([^/?]+)', url, re.IGNORECASE)
    if m:
        return (m.group(1), "group")

    # Numeric profile ID
    m = re.search(r'profile\.php\?id=(\d+)', url, re.IGNORECASE)
    if m:
        return (m.group(1), "profile_id")

    # Page slug (last path segment)
    path = urlparse(url).path.strip("/")
    if path and "/" not in path:
        return (path, "page")

    # Fallback: last path segment
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts:
        return (parts[-1], "page")

    return ("", "unknown")


def extract_ig_handle(url: str) -> str:
    """Extract Instagram handle from a profile URL."""
    if not url:
        return ""
    url = url.strip().rstrip("/")
    m = re.search(r'instagram\.com/([^/?]+)', url, re.IGNORECASE)
    if m:
        handle = m.group(1)
        return handle.lstrip("@")
    return ""


# ─────────────────────────────────────────────────────────────
# Facebook — Meta Graph API
# ─────────────────────────────────────────────────────────────

def get_app_access_token() -> str:
    """Fetch a Facebook app access token."""
    resp = requests.get(
        "https://graph.facebook.com/oauth/access_token",
        params={
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


_fb_token: str | None = None

def fb_token() -> str:
    global _fb_token
    if not _fb_token:
        _fb_token = get_app_access_token()
    return _fb_token


def fetch_fb_page(identifier: str) -> dict:
    """
    Fetch public page data from the Graph API.
    Returns fan_count, name, and recent post dates.
    """
    # Request page basics + last 50 posts
    url = f"{GRAPH_API_BASE}/{identifier}"
    params = {
        "fields": "id,name,fan_count,followers_count,posts.limit(50){created_time,reactions.summary(true),comments.summary(true)}",
        "access_token": fb_token(),
    }
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def process_fb_data(raw: dict) -> dict:
    """Extract structured metrics from raw Graph API response."""
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    cutoff_90d = now - timedelta(days=90)

    posts = raw.get("posts", {}).get("data", [])

    posts_30d = 0
    posts_90d = 0
    last_post_date = None
    total_likes = 0
    total_comments = 0

    for post in posts:
        created = datetime.fromisoformat(post["created_time"].replace("Z", "+00:00"))
        if last_post_date is None or created > last_post_date:
            last_post_date = created
        if created >= cutoff_90d:
            posts_90d += 1
            reactions = post.get("reactions", {}).get("summary", {}).get("total_count", 0)
            comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
            total_likes += reactions
            total_comments += comments
        if created >= cutoff_30d:
            posts_30d += 1

    fan_count = raw.get("fan_count") or raw.get("followers_count") or 0
    avg_likes = round(total_likes / posts_90d, 1) if posts_90d else 0
    avg_comments = round(total_comments / posts_90d, 1) if posts_90d else 0
    engagement_rate = round((total_likes + total_comments) / (fan_count * posts_90d), 4) if fan_count and posts_90d else 0

    return {
        "followers": fan_count,
        "posts_30d": posts_30d,
        "posts_90d": posts_90d,
        "last_post_date": last_post_date.date().isoformat() if last_post_date else None,
        "avg_likes": avg_likes,
        "avg_comments": avg_comments,
        "engagement_rate": engagement_rate,
        "is_active": posts_30d > 0 or posts_90d > 0,
    }


def collect_facebook(org: dict) -> dict | None:
    """
    Collect Facebook metrics for one org.
    Returns structured metrics dict or None on failure.
    """
    fb_url = org.get(ORG_FACEBOOK, "")
    if not fb_url:
        return None

    identifier, fb_type = extract_fb_identifier(fb_url)
    if not identifier:
        log.warning(f"[{org.get(ORG_NAME)}] Could not parse Facebook URL: {fb_url}")
        return None

    if fb_type == "group":
        # Groups don't expose public fan_count — return minimal presence signal
        log.info(f"[{org.get(ORG_NAME)}] Facebook group URL — limited data available")
        return {
            "followers": None,
            "posts_30d": None,
            "posts_90d": None,
            "last_post_date": None,
            "avg_likes": None,
            "avg_comments": None,
            "engagement_rate": None,
            "is_active": True,  # Assume active if they have a group
            "note": "facebook_group_limited_data",
        }

    try:
        raw = fetch_fb_page(identifier)
        metrics = process_fb_data(raw)
        metrics["_raw"] = raw
        return metrics
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            log.warning(f"[{org.get(ORG_NAME)}] Facebook page not found: {identifier}")
        else:
            log.error(f"[{org.get(ORG_NAME)}] Facebook API error: {e}")
        return None
    except Exception as e:
        log.error(f"[{org.get(ORG_NAME)}] Facebook collection failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Instagram — Apify scraper
# ─────────────────────────────────────────────────────────────

def collect_instagram_batch(orgs: list[dict]) -> dict[str, dict]:
    """
    Collect Instagram metrics for multiple orgs in a single Apify run.
    Returns dict of {org_id: metrics}.
    """
    handles = {}
    for org in orgs:
        handle = extract_ig_handle(org.get(ORG_INSTAGRAM, ""))
        if handle:
            handles[handle] = org["_id"]

    if not handles:
        return {}

    log.info(f"Running Apify Instagram scraper for {len(handles)} profiles...")

    # Start Apify actor run
    start_resp = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs",
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
        json={
            "usernames": list(handles.keys()),
            "resultsLimit": 30,  # Recent posts per profile
        },
        timeout=HTTP_TIMEOUT,
    )
    start_resp.raise_for_status()
    run_id = start_resp.json()["data"]["id"]
    log.info(f"  Apify run started: {run_id}")

    # Poll for completion (max 5 minutes)
    for _ in range(60):
        time.sleep(5)
        status_resp = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
            timeout=HTTP_TIMEOUT,
        )
        status = status_resp.json()["data"]["status"]
        if status == "SUCCEEDED":
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            log.error(f"  Apify run {status}")
            return {}
    else:
        log.error("  Apify run timed out waiting for completion")
        return {}

    # Fetch results
    results_resp = requests.get(
        f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
        timeout=30,
    )
    results_resp.raise_for_status()
    items = results_resp.json()

    output = {}
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    cutoff_90d = now - timedelta(days=90)

    for item in items:
        username = item.get("username", "").lower()
        org_id = handles.get(username)
        if not org_id:
            continue

        # Parse post dates from latestPosts
        posts = item.get("latestPosts", [])
        posts_30d, posts_90d = 0, 0
        last_post_date = None
        total_likes, total_comments = 0, 0

        for post in posts:
            ts = post.get("timestamp")
            if ts:
                created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if last_post_date is None or created > last_post_date:
                    last_post_date = created
                if created >= cutoff_90d:
                    posts_90d += 1
                    total_likes += post.get("likesCount", 0)
                    total_comments += post.get("commentsCount", 0)
                if created >= cutoff_30d:
                    posts_30d += 1

        followers = item.get("followersCount", 0)
        avg_likes = round(total_likes / posts_90d, 1) if posts_90d else 0
        avg_comments = round(total_comments / posts_90d, 1) if posts_90d else 0
        engagement_rate = round(
            (total_likes + total_comments) / (followers * posts_90d), 4
        ) if followers and posts_90d else 0

        output[org_id] = {
            "followers": followers,
            "posts_30d": posts_30d,
            "posts_90d": posts_90d,
            "last_post_date": last_post_date.date().isoformat() if last_post_date else None,
            "avg_likes": avg_likes,
            "avg_comments": avg_comments,
            "engagement_rate": engagement_rate,
            "is_active": posts_30d > 0 or posts_90d > 0,
            "_raw": item,
        }

    log.info(f"  Got Instagram data for {len(output)}/{len(handles)} profiles")
    return output


# ─────────────────────────────────────────────────────────────
# Airtable field builders
# ─────────────────────────────────────────────────────────────

def metrics_to_airtable_fields(
    metrics: dict,
    org_id: str,
    platform: str,
    raw_data: Any = None,
) -> dict:
    fields = {
        SM_COLLECTION_DATE: date.today().isoformat(),
        SM_ORGANIZATION:    [org_id],
        SM_PLATFORM:        platform,
        SM_IS_ACTIVE:       bool(metrics.get("is_active")),
    }
    if metrics.get("followers") is not None:
        fields[SM_FOLLOWERS] = metrics["followers"]
    if metrics.get("posts_30d") is not None:
        fields[SM_POSTS_30D] = metrics["posts_30d"]
    if metrics.get("posts_90d") is not None:
        fields[SM_POSTS_90D] = metrics["posts_90d"]
    if metrics.get("last_post_date"):
        fields[SM_LAST_POST_DATE] = metrics["last_post_date"]
    if metrics.get("engagement_rate") is not None:
        fields[SM_ENGAGEMENT_RATE] = metrics["engagement_rate"]
    if metrics.get("avg_likes") is not None:
        fields[SM_AVG_LIKES] = metrics["avg_likes"]
    if metrics.get("avg_comments") is not None:
        fields[SM_AVG_COMMENTS] = metrics["avg_comments"]
    if raw_data:
        # Truncate raw data to stay within Airtable field limits
        raw_str = json.dumps(raw_data, default=str)[:10_000]
        fields[SM_RAW_DATA] = raw_str
    return fields


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AirtableClient()

    orgs = client.get_orgs_with_social()
    log.info(f"Collecting social metrics for {len(orgs)} orgs...")

    summary = {"total": len(orgs), "fb_success": 0, "ig_success": 0, "written": 0}

    # ── Facebook: one org at a time (Graph API is fast) ──
    log.info("--- Facebook ---")
    for i, org in enumerate(orgs, 1):
        if not org.get(ORG_FACEBOOK):
            continue
        org_name = org.get(ORG_NAME, "?")
        log.info(f"[{i}] {org_name}")

        metrics = collect_facebook(org)
        if metrics:
            summary["fb_success"] += 1
            if dry_run:
                print(f"  FB followers={metrics.get('followers')} posts_30d={metrics.get('posts_30d')}")
            else:
                fields = metrics_to_airtable_fields(
                    metrics, org["_id"], "Facebook",
                    raw_data=metrics.get("_raw"),
                )
                try:
                    client.write_social_metric(fields)
                    summary["written"] += 1
                except Exception as e:
                    log.error(f"  Failed to write FB metric for {org_name}: {e}")

        # Be gentle with the Graph API
        time.sleep(0.3)

    # ── Instagram: batch via Apify ──
    log.info("--- Instagram ---")
    ig_orgs = [o for o in orgs if o.get(ORG_INSTAGRAM)]
    if ig_orgs and APIFY_TOKEN:
        ig_results = collect_instagram_batch(ig_orgs)
        for org in ig_orgs:
            metrics = ig_results.get(org["_id"])
            if metrics:
                summary["ig_success"] += 1
                if dry_run:
                    print(f"  IG {org.get(ORG_NAME)}: followers={metrics.get('followers')}")
                else:
                    fields = metrics_to_airtable_fields(
                        metrics, org["_id"], "Instagram",
                        raw_data=metrics.get("_raw"),
                    )
                    try:
                        client.write_social_metric(fields)
                        summary["written"] += 1
                    except Exception as e:
                        log.error(f"  Failed to write IG metric for {org.get(ORG_NAME)}: {e}")
    elif not APIFY_TOKEN:
        log.warning("APIFY_TOKEN not set — skipping Instagram collection")

    log.info(f"Done. FB: {summary['fb_success']}, IG: {summary['ig_success']}, Written: {summary['written']}")
    return summary


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
