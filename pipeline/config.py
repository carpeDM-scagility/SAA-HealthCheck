"""
SAA Org Health Tracker — Configuration
All Airtable field IDs, table IDs, scoring weights, and constants live here.
Update this file if you rename fields in Airtable.
"""

import os

# ─────────────────────────────────────────────────────────────
# Airtable credentials (set as environment variables or GitHub secrets)
# ─────────────────────────────────────────────────────────────
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = "app6ACspUBzaoNnAQ"

# ─────────────────────────────────────────────────────────────
# Table IDs
# ─────────────────────────────────────────────────────────────
TABLE_ORGANIZATIONS  = "tblgKYNjvlQNU9I24"
TABLE_HEALTH_SCORES  = "tblKFO3HpkoOO5HPj"
TABLE_SOCIAL_METRICS = "tblSw6F4oZNH99xSF"
TABLE_FINANCIAL      = "tblj8lKAPrJl9Xn5A"

# ─────────────────────────────────────────────────────────────
# Organizations — field IDs
# ─────────────────────────────────────────────────────────────
ORG_NAME         = "fldq57nc4EWYzPHWJ"
ORG_WEBSITE      = "fldmSdoEQJWeiA21p"
ORG_FACEBOOK     = "fldJmri85xmMUD9IH"
ORG_INSTAGRAM    = "flduJOtgYnFtOkUxo"
ORG_EMAIL        = "fldfNnzXXgJwDsvPu"
ORG_EIN          = "fldO8m4pd5pi0S5cQ"
ORG_STATE        = "fldhcuHfhKzXdvSRo"
ORG_SCOPE        = "fld0N0AdEmxYDlAMX"
ORG_HEALTH_SCORE = "fld3vKoXPcKYtU7st"
ORG_HEALTH_TIER  = "fldKXHE9igr9m3fCs"
ORG_LAST_SCORED  = "fldWe3qFg6GRlFgfQ"

# ─────────────────────────────────────────────────────────────
# Health Scores — field IDs
# ─────────────────────────────────────────────────────────────
HS_SCORE_DATE      = "fldfRse6kswEikoVr"
HS_ORGANIZATION    = "fldagIiV0cZWAjyjM"
HS_TOTAL_SCORE     = "fldjy6gQcaeG8YM6n"
HS_HEALTH_TIER     = "fldFpy61aH2F3EJlB"
HS_PRESENCE_SCORE  = "fldjW6gUeKb6ZuM7k"
HS_ACTIVITY_SCORE  = "fld5dgn47kqG9ZdJ9"
HS_REACH_SCORE     = "fldlrDINXmo9Hnn5q"
HS_FINANCIAL_SCORE = "fldJ1AsXpa2mCODOt"
HS_QOQ_CHANGE      = "fldOS3JaPtjdBFzAx"
HS_TREND           = "fldWnZPmHTkbofVqU"
HS_NOTES           = "fldrn8TVE7kcdSdJ8"

# ─────────────────────────────────────────────────────────────
# Social Metrics — field IDs
# ─────────────────────────────────────────────────────────────
SM_COLLECTION_DATE   = "fldscJ4YW6BI2stye"
SM_ORGANIZATION      = "fldo1L7eWiqfQfWVK"
SM_PLATFORM          = "fld2PNRo7gldvuCTg"
SM_IS_ACTIVE         = "fld4vx6rdIiGxHYPz"
SM_FOLLOWERS         = "fld72IXEWj799yEnu"
SM_POSTS_30D         = "fldnPZ04LuD3eD7Vp"
SM_POSTS_90D         = "fldoJfodMXGytagU2"
SM_LAST_POST_DATE    = "fldDoD1q5FFvcKDBv"
SM_ENGAGEMENT_RATE   = "fldE0ITj9bsJrzI1O"
SM_AVG_LIKES         = "fld2XuLBlj5SHPji7"
SM_AVG_COMMENTS      = "fldpj45T2LSAUwpV9"
SM_FOLLOWER_GROWTH   = "fldUGCnKQJDQQsr3M"
SM_RAW_DATA          = "fldIB6uQPcYAZURRZ"

# ─────────────────────────────────────────────────────────────
# Financial Metrics — field IDs
# ─────────────────────────────────────────────────────────────
FIN_TAX_YEAR        = "fldF1ILKkl3toJc5d"
FIN_ORGANIZATION    = "fldr9AqgjimCtZ0xQ"
FIN_TOTAL_REVENUE   = "fld7tQ6ZXfr2JFIo4"
FIN_TOTAL_EXPENSES  = "fld1upIl1Uk0SZ5Tc"
FIN_PROGRAM_EXP     = "fldr8DyYBFwlGHGXD"
FIN_NET_ASSETS      = "fldQr4kbzdqyXZn7O"
FIN_PROGRAM_RATIO   = "fldDWA77ouf5tH7Z9"
FIN_REVENUE_YOY     = "fldaYWUpzbV7CvpLz"
FIN_NUM_EMPLOYEES   = "fldxYpijCUZC8BwjA"
FIN_DATA_SOURCE     = "fld97kZoKJhgA67QJ"
FIN_FILING_DATE     = "fldaPqQErE43E7sCZ"
FIN_EIN_VERIFIED    = "fldB2q7QYv8blPjiY"

# ─────────────────────────────────────────────────────────────
# Scoring weights (must sum to 1.0)
# ─────────────────────────────────────────────────────────────
WEIGHTS_WITH_FINANCIAL = {
    "presence":  0.25,
    "activity":  0.30,
    "reach":     0.25,
    "financial": 0.20,
}

# Reweighted when no 990 data is available
WEIGHTS_NO_FINANCIAL = {
    "presence": 0.30,
    "activity": 0.38,
    "reach":    0.32,
}

# Health tier thresholds
TIER_HEALTHY  = 75
TIER_STABLE   = 50
TIER_AT_RISK  = 25
# Below 25 = Critical

# ─────────────────────────────────────────────────────────────
# External API credentials (set as environment variables)
# ─────────────────────────────────────────────────────────────
META_APP_ID     = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
APIFY_TOKEN     = os.environ.get("APIFY_TOKEN", "")

# Request timeouts (seconds)
HTTP_TIMEOUT = 15
