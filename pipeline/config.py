"""
SAA Org Health Tracker — Configuration
Column names match the Supabase schema exactly.
Update this file if you rename columns in Supabase.
"""

import os

# ─────────────────────────────────────────────────────────────
# Supabase credentials (set as environment variables / GitHub secrets)
# ─────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─────────────────────────────────────────────────────────────
# Table names
# ─────────────────────────────────────────────────────────────
TABLE_ORGANIZATIONS  = "organizations"
TABLE_HEALTH_SCORES  = "health_scores"
TABLE_SOCIAL_METRICS = "social_metrics"
TABLE_FINANCIAL      = "financial_metrics"

# ─────────────────────────────────────────────────────────────
# Organizations — column names
# ─────────────────────────────────────────────────────────────
ORG_NAME         = "name"
ORG_WEBSITE      = "website_url"
ORG_FACEBOOK     = "facebook_url"
ORG_INSTAGRAM    = "instagram_url"
ORG_EMAIL        = "email"
ORG_EIN          = "ein"
ORG_STATE        = "state"
ORG_SCOPE        = "scope"
ORG_HEALTH_SCORE = "health_score"
ORG_HEALTH_TIER  = "health_tier"
ORG_LAST_SCORED  = "last_scored"

# ─────────────────────────────────────────────────────────────
# Social Metrics — column names
# ─────────────────────────────────────────────────────────────
SM_COLLECTION_DATE = "collected_on"
SM_ORGANIZATION    = "organization_id"
SM_PLATFORM        = "platform"
SM_IS_ACTIVE       = "is_active"
SM_FOLLOWERS       = "followers"
SM_POSTS_30D       = "posts_30d"
SM_POSTS_90D       = "posts_90d"
SM_LAST_POST_DATE  = "last_post_date"
SM_ENGAGEMENT_RATE = "engagement_rate"
SM_AVG_LIKES       = "avg_likes"
SM_AVG_COMMENTS    = "avg_comments"
SM_FOLLOWER_GROWTH = "follower_growth"
SM_RAW_DATA        = "raw_data"

# ─────────────────────────────────────────────────────────────
# Financial Metrics — column names
# ─────────────────────────────────────────────────────────────
FIN_TAX_YEAR     = "tax_year"
FIN_ORGANIZATION = "organization_id"
FIN_TOTAL_REVENUE   = "total_revenue"
FIN_TOTAL_EXPENSES  = "total_expenses"
FIN_PROGRAM_EXP     = "program_expenses"
FIN_NET_ASSETS      = "net_assets"
FIN_PROGRAM_RATIO   = "program_ratio"
FIN_REVENUE_YOY     = "revenue_yoy"
FIN_NUM_EMPLOYEES   = "num_employees"
FIN_FILING_DATE     = "filing_date"
FIN_EIN_VERIFIED    = "ein_verified"

# ─────────────────────────────────────────────────────────────
# Health Scores — column names
# ─────────────────────────────────────────────────────────────
HS_SCORE_DATE      = "scored_on"
HS_ORGANIZATION    = "organization_id"
HS_TOTAL_SCORE     = "total_score"
HS_HEALTH_TIER     = "health_tier"
HS_PRESENCE_SCORE  = "presence_score"
HS_ACTIVITY_SCORE  = "activity_score"
HS_REACH_SCORE     = "reach_score"
HS_FINANCIAL_SCORE = "financial_score"
HS_QOQ_CHANGE      = "qoq_change"
HS_TREND           = "trend"
HS_NOTES           = "notes"

# ─────────────────────────────────────────────────────────────
# Scoring weights (must sum to 1.0)
# ─────────────────────────────────────────────────────────────
WEIGHTS_WITH_FINANCIAL = {
    "presence":  0.25,
    "activity":  0.30,
    "reach":     0.25,
    "financial": 0.20,
}

WEIGHTS_NO_FINANCIAL = {
    "presence": 0.30,
    "activity": 0.38,
    "reach":    0.32,
}

# Health tier thresholds
TIER_HEALTHY = 75
TIER_STABLE  = 50
TIER_AT_RISK = 25

# ─────────────────────────────────────────────────────────────
# External API credentials
# ─────────────────────────────────────────────────────────────
META_APP_ID     = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
APIFY_TOKEN     = os.environ.get("APIFY_TOKEN", "")

HTTP_TIMEOUT = 15
