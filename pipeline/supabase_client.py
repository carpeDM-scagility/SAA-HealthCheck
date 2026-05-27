"""
SAA Org Health Tracker — Supabase Client
Talks to Supabase via its PostgREST HTTP API using plain requests.
No supabase Python package required — works on any Python version.
"""

from __future__ import annotations
import logging
from datetime import date
from typing import Any

import requests

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    TABLE_ORGANIZATIONS, TABLE_HEALTH_SCORES,
    TABLE_SOCIAL_METRICS, TABLE_FINANCIAL,
    ORG_NAME, ORG_WEBSITE, ORG_FACEBOOK, ORG_INSTAGRAM,
    ORG_EMAIL, ORG_EIN, ORG_STATE, ORG_SCOPE,
    ORG_HEALTH_SCORE, ORG_HEALTH_TIER, ORG_LAST_SCORED,
    SM_ORGANIZATION, SM_COLLECTION_DATE,
    FIN_ORGANIZATION, FIN_TAX_YEAR,
    HS_ORGANIZATION, HS_SCORE_DATE, HS_TOTAL_SCORE,
)

log = logging.getLogger(__name__)

ORG_SELECT = ",".join([
    "id", ORG_NAME, ORG_WEBSITE, ORG_FACEBOOK, ORG_INSTAGRAM,
    ORG_EMAIL, ORG_EIN, ORG_STATE, ORG_SCOPE,
    ORG_HEALTH_SCORE, ORG_HEALTH_TIER, ORG_LAST_SCORED,
])


class DbClient:
    def __init__(self):
        self.base = SUPABASE_URL.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
        }

    # ── Low-level HTTP helpers ───────────────────────────────

    def _get(self, table: str, params: dict | None = None) -> list[dict]:
        resp = requests.get(
            f"{self.base}/{table}",
            headers=self.headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, table: str, data: dict | list, upsert_on: str | None = None) -> dict:
        prefer = "return=representation"
        if upsert_on:
            prefer = f"resolution=merge-duplicates,return=representation"
        headers = {**self.headers, "Prefer": prefer}
        if upsert_on:
            headers["on-conflict"] = upsert_on
        resp = requests.post(
            f"{self.base}/{table}",
            headers=headers,
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        return result[0] if isinstance(result, list) and result else (result or {})

    def _patch(self, table: str, eq_col: str, eq_val: str, data: dict) -> None:
        resp = requests.patch(
            f"{self.base}/{table}",
            headers={**self.headers, "Prefer": "return=minimal"},
            params={eq_col: f"eq.{eq_val}"},
            json=data,
            timeout=30,
        )
        resp.raise_for_status()

    # ── Helpers ──────────────────────────────────────────────

    def _clean(self, fields: dict) -> dict:
        """Unwrap Airtable-style [uuid] linked record lists → plain uuid string."""
        cleaned = {}
        for k, v in fields.items():
            if isinstance(v, list) and len(v) == 1:
                cleaned[k] = v[0]
            elif v is not None:
                cleaned[k] = v
        return cleaned

    def _flatten(self, record: dict) -> dict:
        flat = dict(record)
        flat["_id"] = flat.get("id", "")
        return flat

    # ── Organizations ────────────────────────────────────────

    def get_all_orgs(self) -> list[dict]:
        rows = self._get(TABLE_ORGANIZATIONS, {
            "select": ORG_SELECT,
            "order":  f"{ORG_NAME}.asc",
        })
        return [self._flatten(r) for r in rows]

    def get_orgs_with_websites(self) -> list[dict]:
        rows = self._get(TABLE_ORGANIZATIONS, {
            "select":    ORG_SELECT,
            ORG_WEBSITE: "not.is.null",
        })
        # Extra guard: skip empty strings
        return [self._flatten(r) for r in rows if r.get(ORG_WEBSITE)]

    def get_orgs_with_social(self) -> list[dict]:
        return [
            o for o in self.get_all_orgs()
            if o.get(ORG_FACEBOOK) or o.get(ORG_INSTAGRAM)
        ]

    def get_orgs_with_ein(self) -> list[dict]:
        rows = self._get(TABLE_ORGANIZATIONS, {
            "select": ORG_SELECT,
            ORG_EIN:  "not.is.null",
        })
        return [self._flatten(r) for r in rows if r.get(ORG_EIN)]

    def get_orgs_without_ein(self) -> list[dict]:
        return [o for o in self.get_all_orgs() if not o.get(ORG_EIN)]

    def update_org_score(self, record_id: str, score: float, tier: str) -> None:
        self._patch(TABLE_ORGANIZATIONS, "id", record_id, {
            ORG_HEALTH_SCORE: round(score, 1),
            ORG_HEALTH_TIER:  tier,
            ORG_LAST_SCORED:  date.today().isoformat(),
        })

    def update_org_ein(self, record_id: str, ein: str) -> None:
        self._patch(TABLE_ORGANIZATIONS, "id", record_id, {ORG_EIN: ein})

    # ── Social Metrics ───────────────────────────────────────

    def write_social_metric(self, fields: dict) -> dict:
        return self._post(TABLE_SOCIAL_METRICS, self._clean(fields))

    def get_social_metrics_for_org(self, org_id: str, limit: int = 6) -> list[dict]:
        return self._get(TABLE_SOCIAL_METRICS, {
            "select":           "*",
            SM_ORGANIZATION:    f"eq.{org_id}",
            "order":            f"{SM_COLLECTION_DATE}.desc",
            "limit":            limit,
        })

    # ── Financial Metrics ────────────────────────────────────

    def write_financial_metric(self, fields: dict) -> dict:
        return self._post(
            TABLE_FINANCIAL,
            self._clean(fields),
            upsert_on="organization_id,tax_year",
        )

    def get_financial_for_org(self, org_id: str) -> list[dict]:
        return self._get(TABLE_FINANCIAL, {
            "select":        "*",
            FIN_ORGANIZATION: f"eq.{org_id}",
            "order":         f"{FIN_TAX_YEAR}.desc",
        })

    # ── Health Scores ────────────────────────────────────────

    def write_health_score(self, fields: dict) -> dict:
        return self._post(TABLE_HEALTH_SCORES, self._clean(fields))

    def get_health_scores_for_org(self, org_id: str, limit: int = 4) -> list[dict]:
        return self._get(TABLE_HEALTH_SCORES, {
            "select":        "*",
            HS_ORGANIZATION: f"eq.{org_id}",
            "order":         f"{HS_SCORE_DATE}.desc",
            "limit":         limit,
        })
