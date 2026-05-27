"""
SAA Org Health Tracker — Scoring Engine
Reads the latest Social Metrics and Financial Metrics for each org
and computes a composite health score (0–100) across four domains.
Writes results to Health Scores and updates Organizations.
"""

from __future__ import annotations
import logging
from datetime import date, datetime, timedelta
from typing import Any

from supabase_client import DbClient as AirtableClient
from config import (
    ORG_NAME, ORG_EIN, ORG_WEBSITE, ORG_FACEBOOK, ORG_INSTAGRAM,
    SM_PLATFORM, SM_IS_ACTIVE, SM_FOLLOWERS, SM_POSTS_30D,
    SM_POSTS_90D, SM_LAST_POST_DATE, SM_ENGAGEMENT_RATE,
    SM_AVG_LIKES, SM_AVG_COMMENTS, SM_FOLLOWER_GROWTH, SM_RAW_DATA,
    FIN_TAX_YEAR, FIN_PROGRAM_RATIO, FIN_REVENUE_YOY,
    FIN_TOTAL_REVENUE, FIN_TOTAL_EXPENSES, FIN_NET_ASSETS,
    HS_SCORE_DATE, HS_ORGANIZATION, HS_TOTAL_SCORE, HS_HEALTH_TIER,
    HS_PRESENCE_SCORE, HS_ACTIVITY_SCORE, HS_REACH_SCORE,
    HS_FINANCIAL_SCORE, HS_QOQ_CHANGE, HS_TREND, HS_NOTES,
    WEIGHTS_WITH_FINANCIAL, WEIGHTS_NO_FINANCIAL,
    TIER_HEALTHY, TIER_STABLE, TIER_AT_RISK,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Domain scoring functions
# ─────────────────────────────────────────────────────────────

def score_presence(org: dict, website_metric: dict | None) -> float:
    """
    Domain 1 — Digital Presence (0–100)
    Is the org findable and reachable online?
    """
    score = 0.0

    # Website exists and is live
    has_website = bool(org.get(ORG_WEBSITE))
    website_live = website_metric and website_metric.get(SM_IS_ACTIVE)
    if has_website and website_live:
        score += 40
    elif has_website:
        score += 15  # Has URL but appears down

    # SSL valid (from raw data)
    if website_live:
        raw = website_metric.get(SM_RAW_DATA, "")
        if "'ssl_valid': True" in str(raw):
            score += 10

    # Social profiles exist
    if org.get(ORG_FACEBOOK):
        score += 20
    if org.get(ORG_INSTAGRAM):
        score += 20

    # Has contact info / email
    has_email = bool(org.get("Email"))
    has_contact_on_site = website_live and "'has_contact': True" in str(
        website_metric.get(SM_RAW_DATA, "")
    )
    if has_email or has_contact_on_site:
        score += 10

    return min(score, 100.0)


def score_activity(social_metrics: list[dict]) -> float:
    """
    Domain 2 — Content Activity (0–100)
    How recently and frequently is the org posting?
    """
    if not social_metrics:
        return 0.0

    today = date.today()

    # Find the most recent post across all platforms
    last_post_date = None
    total_posts_30d = 0
    total_posts_90d = 0

    for metric in social_metrics:
        if not metric.get(SM_IS_ACTIVE):
            continue
        lp = metric.get(SM_LAST_POST_DATE)
        if lp:
            lp_date = date.fromisoformat(lp) if isinstance(lp, str) else lp
            if last_post_date is None or lp_date > last_post_date:
                last_post_date = lp_date
        total_posts_30d += metric.get(SM_POSTS_30D) or 0
        total_posts_90d += metric.get(SM_POSTS_90D) or 0

    # Recency score (60% weight)
    if last_post_date:
        days_since = (today - last_post_date).days
        if days_since <= 7:
            recency = 100
        elif days_since <= 14:
            recency = 80
        elif days_since <= 30:
            recency = 60
        elif days_since <= 60:
            recency = 40
        elif days_since <= 90:
            recency = 20
        else:
            recency = 0
    else:
        recency = 0

    # Frequency score (40% weight) — posts per 90 days
    if total_posts_90d >= 24:       # 2+ per week
        frequency = 100
    elif total_posts_90d >= 12:     # ~1 per week
        frequency = 80
    elif total_posts_90d >= 6:      # biweekly
        frequency = 60
    elif total_posts_90d >= 3:
        frequency = 40
    elif total_posts_90d >= 1:
        frequency = 20
    else:
        frequency = 0

    return round(recency * 0.60 + frequency * 0.40, 1)


def score_reach(social_metrics: list[dict]) -> float:
    """
    Domain 3 — Community Reach (0–100)
    How large and growing is the org's online following?
    """
    if not social_metrics:
        return 0.0

    total_followers = sum(
        m.get(SM_FOLLOWERS) or 0
        for m in social_metrics
        if m.get(SM_IS_ACTIVE)
    )

    # Engagement rate: average across platforms that have it
    engagement_rates = [
        m.get(SM_ENGAGEMENT_RATE) or 0
        for m in social_metrics
        if m.get(SM_ENGAGEMENT_RATE) is not None and m.get(SM_IS_ACTIVE)
    ]
    avg_engagement = (
        sum(engagement_rates) / len(engagement_rates)
        if engagement_rates else 0
    )

    # Growth signal
    growth_rates = [
        m.get(SM_FOLLOWER_GROWTH) or 0
        for m in social_metrics
        if m.get(SM_FOLLOWER_GROWTH) is not None
    ]
    avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0

    # Follower count score (70% weight)
    # Calibrated for small community nonprofits, not national brands
    if total_followers >= 5000:
        follower_score = 100
    elif total_followers >= 2000:
        follower_score = 80
    elif total_followers >= 1000:
        follower_score = 60
    elif total_followers >= 500:
        follower_score = 45
    elif total_followers >= 200:
        follower_score = 30
    elif total_followers >= 50:
        follower_score = 15
    else:
        follower_score = 5

    # Growth bonus/penalty (20% weight)
    if avg_growth >= 0.05:      # >5% growth
        growth_score = 100
    elif avg_growth >= 0.02:
        growth_score = 75
    elif avg_growth >= 0:
        growth_score = 50
    elif avg_growth >= -0.05:
        growth_score = 25
    else:
        growth_score = 0

    # Engagement bonus (10% weight)
    if avg_engagement >= 0.05:     # >5% engagement rate is excellent for nonprofits
        engagement_score = 100
    elif avg_engagement >= 0.02:
        engagement_score = 70
    elif avg_engagement >= 0.01:
        engagement_score = 40
    elif avg_engagement > 0:
        engagement_score = 20
    else:
        engagement_score = 0

    return round(
        follower_score * 0.70
        + growth_score * 0.20
        + engagement_score * 0.10,
        1,
    )


def score_financial(financial_records: list[dict]) -> float | None:
    """
    Domain 4 — Financial Health (0–100)
    Returns None if no 990 data available (score will be excluded from composite).
    """
    if not financial_records:
        return None

    # Use the most recent filing
    latest = financial_records[0]
    prior = financial_records[1] if len(financial_records) > 1 else None

    program_ratio = latest.get(FIN_PROGRAM_RATIO)
    revenue_yoy = latest.get(FIN_REVENUE_YOY)
    total_expenses = latest.get(FIN_TOTAL_EXPENSES) or 0
    net_assets = latest.get(FIN_NET_ASSETS)

    # Program efficiency score (50% weight)
    # Higher = more $ going to programs vs. admin
    if program_ratio is not None:
        if program_ratio >= 0.80:
            efficiency_score = 100
        elif program_ratio >= 0.70:
            efficiency_score = 85
        elif program_ratio >= 0.60:
            efficiency_score = 70
        elif program_ratio >= 0.50:
            efficiency_score = 50
        elif program_ratio >= 0.40:
            efficiency_score = 30
        else:
            efficiency_score = 10
    else:
        efficiency_score = 50  # Unknown — assume average

    # Revenue trend score (30% weight)
    if revenue_yoy is not None:
        if revenue_yoy >= 0.15:    # >15% growth
            trend_score = 100
        elif revenue_yoy >= 0.05:
            trend_score = 80
        elif revenue_yoy >= 0:
            trend_score = 60
        elif revenue_yoy >= -0.10:
            trend_score = 35
        else:
            trend_score = 10
    else:
        trend_score = 50  # Unknown — assume average

    # Runway / reserves score (20% weight)
    # Net assets as a multiple of monthly expenses
    if total_expenses > 0 and net_assets is not None:
        monthly_burn = total_expenses / 12
        months_runway = net_assets / monthly_burn if monthly_burn > 0 else 0
        if months_runway >= 12:
            reserves_score = 100
        elif months_runway >= 6:
            reserves_score = 80
        elif months_runway >= 3:
            reserves_score = 60
        elif months_runway >= 1:
            reserves_score = 35
        elif months_runway >= 0:
            reserves_score = 15
        else:
            reserves_score = 0  # Negative net assets
    else:
        reserves_score = 50  # Unknown

    return round(
        efficiency_score * 0.50
        + trend_score * 0.30
        + reserves_score * 0.20,
        1,
    )


# ─────────────────────────────────────────────────────────────
# Composite scoring
# ─────────────────────────────────────────────────────────────

def compute_composite(
    presence: float,
    activity: float,
    reach: float,
    financial: float | None,
) -> tuple[float, dict]:
    """Compute weighted composite score. Returns (total, weights_used)."""
    if financial is not None:
        weights = WEIGHTS_WITH_FINANCIAL
        total = (
            presence  * weights["presence"]
            + activity  * weights["activity"]
            + reach     * weights["reach"]
            + financial * weights["financial"]
        )
    else:
        weights = WEIGHTS_NO_FINANCIAL
        total = (
            presence * weights["presence"]
            + activity * weights["activity"]
            + reach    * weights["reach"]
        )
    return round(total, 1), weights


def score_to_tier(score: float) -> str:
    if score >= TIER_HEALTHY:
        return "Healthy"
    elif score >= TIER_STABLE:
        return "Stable"
    elif score >= TIER_AT_RISK:
        return "At Risk"
    else:
        return "Critical"


def compute_trend(current: float, prior: float | None) -> str:
    if prior is None:
        return "Stable"
    delta = current - prior
    if delta >= 5:
        return "Improving"
    elif delta <= -5:
        return "Declining"
    else:
        return "Stable"


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def score_org(org: dict, client: AirtableClient) -> dict | None:
    """Score a single org. Returns result dict or None on failure."""
    org_id = org["_id"]
    org_name = org.get(ORG_NAME, "?")

    # Fetch latest data
    social_records = client.get_social_metrics_for_org(org_id, limit=6)
    financial_records = client.get_financial_for_org(org_id)
    prior_scores = client.get_health_scores_for_org(org_id, limit=2)

    # Split social by platform
    website_metrics = next(
        (m for m in social_records if m.get(SM_PLATFORM) == "Website"), None
    )
    active_social = [
        m for m in social_records
        if m.get(SM_PLATFORM) in ("Facebook", "Instagram")
    ]

    # If we have no data at all, skip
    if not social_records and not financial_records:
        log.warning(f"  [{org_name}] No data available — skipping")
        return None

    # Score each domain
    presence  = score_presence(org, website_metrics)
    activity  = score_activity(active_social)
    reach     = score_reach(active_social)
    financial = score_financial(financial_records)

    total, weights = compute_composite(presence, activity, reach, financial)
    tier = score_to_tier(total)

    # QoQ change and trend
    prior_score = prior_scores[0].get(HS_TOTAL_SCORE) if prior_scores else None
    qoq_change = round(total - prior_score, 1) if prior_score is not None else None
    trend = compute_trend(total, prior_score)

    # Build notes
    notes_parts = []
    if financial is None:
        notes_parts.append("No 990 data — financial domain excluded, weights redistributed")
    if not active_social:
        notes_parts.append("No social metrics — activity and reach based on website only")
    notes = "; ".join(notes_parts) if notes_parts else "All domains scored"

    return {
        "org_id": org_id,
        "org_name": org_name,
        "total": total,
        "tier": tier,
        "presence": presence,
        "activity": activity,
        "reach": reach,
        "financial": financial,
        "qoq_change": qoq_change,
        "trend": trend,
        "notes": notes,
    }


def run(dry_run: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AirtableClient()

    orgs = client.get_all_orgs()
    log.info(f"Scoring {len(orgs)} orgs...")

    today = date.today().isoformat()
    summary = {
        "total": len(orgs), "scored": 0, "skipped": 0,
        "healthy": 0, "stable": 0, "at_risk": 0, "critical": 0,
    }

    for i, org in enumerate(orgs, 1):
        org_name = org.get(ORG_NAME, "?")
        log.info(f"[{i}/{len(orgs)}] {org_name}")

        result = score_org(org, client)
        if not result:
            summary["skipped"] += 1
            continue

        summary["scored"] += 1
        tier_key = result["tier"].lower().replace(" ", "_")
        summary[tier_key] = summary.get(tier_key, 0) + 1

        if dry_run:
            fin_str = f"fin={result['financial']:.1f}" if result["financial"] else "fin=N/A"
            print(
                f"  {result['tier']:8s} {result['total']:5.1f} | "
                f"pres={result['presence']:.1f} act={result['activity']:.1f} "
                f"reach={result['reach']:.1f} {fin_str} | "
                f"trend={result['trend']}"
            )
            continue

        # Write to Health Scores table
        hs_fields = {
            HS_SCORE_DATE:      today,
            HS_ORGANIZATION:    [result["org_id"]],
            HS_TOTAL_SCORE:     result["total"],
            HS_HEALTH_TIER:     result["tier"],
            HS_PRESENCE_SCORE:  result["presence"],
            HS_ACTIVITY_SCORE:  result["activity"],
            HS_REACH_SCORE:     result["reach"],
            HS_TREND:           result["trend"],
            HS_NOTES:           result["notes"],
        }
        if result["financial"] is not None:
            hs_fields[HS_FINANCIAL_SCORE] = result["financial"]
        if result["qoq_change"] is not None:
            hs_fields[HS_QOQ_CHANGE] = result["qoq_change"]

        try:
            client.write_health_score(hs_fields)
        except Exception as e:
            log.error(f"  Failed to write health score: {e}")
            continue

        # Update Organizations with current score + tier
        try:
            client.update_org_score(result["org_id"], result["total"], result["tier"])
        except Exception as e:
            log.error(f"  Failed to update org score field: {e}")

    log.info(
        f"Done. Scored: {summary['scored']}, Skipped: {summary['skipped']} | "
        f"Healthy: {summary.get('healthy', 0)}, Stable: {summary.get('stable', 0)}, "
        f"At Risk: {summary.get('at_risk', 0)}, Critical: {summary.get('critical', 0)}"
    )
    return summary


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
