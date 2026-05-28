"""
SAA Org Health Tracker — Airtable Client
Thin wrapper around pyairtable for common read/write operations.
"""

from __future__ import annotations
import logging
from datetime import date
from typing import Any

from pyairtable import Api
from config import (
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID,
    TABLE_ORGANIZATIONS, TABLE_HEALTH_SCORES,
    TABLE_SOCIAL_METRICS, TABLE_FINANCIAL,
    ORG_NAME, ORG_WEBSITE, ORG_FACEBOOK, ORG_INSTAGRAM,
    ORG_EMAIL, ORG_EIN, ORG_STATE, ORG_SCOPE,
    ORG_HEALTH_SCORE, ORG_HEALTH_TIER, ORG_LAST_SCORED,
    SM_COLLECTION_DATE, SM_ORGANIZATION,
    FIN_TAX_YEAR, FIN_ORGANIZATION,
    HS_SCORE_DATE, HS_ORGANIZATION,
)

log = logging.getLogger(__name__)


class AirtableClient:
    def __init__(self):
        # use_field_ids=True: Airtable returns field IDs as keys, matching our config constants
        api = Api(AIRTABLE_API_KEY, use_field_ids=True)
        self.orgs      = api.table(AIRTABLE_BASE_ID, TABLE_ORGANIZATIONS)
        self.scores    = api.table(AIRTABLE_BASE_ID, TABLE_HEALTH_SCORES)
        self.social    = api.table(AIRTABLE_BASE_ID, TABLE_SOCIAL_METRICS)
        self.financial = api.table(AIRTABLE_BASE_ID, TABLE_FINANCIAL)

    # ── Organizations ────────────────────────────────────────

    def get_all_orgs(self) -> list[dict]:
        """Return all org records with their key fields."""
        fields = [
            ORG_NAME, ORG_WEBSITE, ORG_FACEBOOK, ORG_INSTAGRAM,
            ORG_EMAIL, ORG_EIN, ORG_STATE, ORG_SCOPE,
            ORG_HEALTH_SCORE, ORG_HEALTH_TIER, ORG_LAST_SCORED,
        ]
        records = self.orgs.all(fields=fields)
        return [self._flatten(r) for r in records]

    def get_orgs_with_websites(self) -> list[dict]:
        return [o for o in self.get_all_orgs() if o.get(ORG_WEBSITE)]

    def get_orgs_with_social(self) -> list[dict]:
        return [
            o for o in self.get_all_orgs()
            if o.get(ORG_FACEBOOK) or o.get(ORG_INSTAGRAM)
        ]

    def get_orgs_with_ein(self) -> list[dict]:
        return [o for o in self.get_all_orgs() if o.get(ORG_EIN)]

    def get_orgs_without_ein(self) -> list[dict]:
        return [o for o in self.get_all_orgs() if not o.get(ORG_EIN)]

    def update_org_ein(self, record_id: str, ein: str) -> None:
        self.orgs.update(record_id, {ORG_EIN: ein})

    def update_org_score(self, record_id: str, score: float, tier: str) -> None:
        self.orgs.update(record_id, {
            ORG_HEALTH_SCORE: round(score, 1),
            ORG_HEALTH_TIER:  tier,
            ORG_LAST_SCORED:  date.today().isoformat(),
        })

    # ── Social Metrics ───────────────────────────────────────

    def write_social_metric(self, fields: dict) -> dict:
        return self.social.create(fields)

    def get_social_metrics_for_org(self, org_record_id: str, limit: int = 6) -> list[dict]:
        """Get the most recent social metric snapshots for an org."""
        # pyairtable v2: prefix field ID with "-" for descending sort
        records = self.social.all(
            sort=[f"-{SM_COLLECTION_DATE}"]
        )
        org_records = [
            self._flatten(r) for r in records
            if org_record_id in (r["fields"].get(SM_ORGANIZATION) or [])
        ]
        return org_records[:limit]

    # ── Financial Metrics ────────────────────────────────────

    def write_financial_metric(self, fields: dict) -> dict:
        return self.financial.create(fields)

    def get_financial_for_org(self, org_record_id: str) -> list[dict]:
        """Get all financial records for an org, sorted by tax year desc."""
        records = self.financial.all(
            sort=[f"-{FIN_TAX_YEAR}"]
        )
        return [
            self._flatten(r) for r in records
            if org_record_id in (r["fields"].get(FIN_ORGANIZATION) or [])
        ]

    # ── Health Scores ────────────────────────────────────────

    def write_health_score(self, fields: dict) -> dict:
        return self.scores.create(fields)

    def get_health_scores_for_org(self, org_record_id: str, limit: int = 4) -> list[dict]:
        records = self.scores.all(
            sort=[f"-{HS_SCORE_DATE}"]
        )
        org_records = [
            self._flatten(r) for r in records
            if org_record_id in (r["fields"].get(HS_ORGANIZATION) or [])
        ]
        return org_records[:limit]

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _flatten(record: dict) -> dict:
        """Merge record id + fields into a single flat dict."""
        flat = {"_id": record["id"]}
        flat.update(record.get("fields", {}))
        return flat
