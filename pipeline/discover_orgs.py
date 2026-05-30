"""
SAA Org Discovery — ProPublica + Claude Classifier
Searches ProPublica Nonprofit Explorer for South Asian American organizations,
classifies each one with Claude, and inserts approved candidates into
pending_submissions for human review in the Banyan dashboard.

Usage:
  python discover_orgs.py                      # dry run (no writes)
  python discover_orgs.py --write              # insert into Supabase
  python discover_orgs.py --state CA           # one state only
  python discover_orgs.py --limit 50           # cap total candidates processed
  python discover_orgs.py --query "Tamil"      # single search term
  python discover_orgs.py --min-confidence 0.9 # stricter threshold

Env vars required:
  SUPABASE_URL        your Supabase project URL
  SUPABASE_KEY        Supabase service role key
  ANTHROPIC_API_KEY   Anthropic API key (claude-haiku for cost efficiency)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Optional
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

log = logging.getLogger(__name__)

# ── Search configuration ──────────────────────────────────────────────────────

# Terms we send to ProPublica search. Broad on purpose — Claude filters false positives.
DEFAULT_QUERIES = [
    # Broad umbrella
    "south asian",
    "desi",

    # Indian subcontinent — "indian american" for adjective form,
    # "india" for orgs named "India Community Center" / "India Organization" etc.
    # ProPublica is nonprofits-only so "india" noise is manageable.
    # "indo american" catches a third naming convention.
    "indian american",
    "india",
    "indo american",

    # Country roots — catches both noun and adjective form in one query
    # (e.g. "pakistan" matches "Pakistan Forum" AND "Pakistani Community Center")
    "pakistan",
    "bangladesh",
    "nepal",
    "sri lanka",

    # Use geographic root where the community name derives from it —
    # more inclusive than the adjective alone.
    "gujarat",      # catches Gujarat AND Gujarati
    "punjab",       # catches Punjab AND Punjabi
    "kashmir",      # catches Kashmir AND Kashmiri
    "sindh",        # catches Sindh AND Sindhi
    "kerala",       # catches Kerala-based Malayali orgs
    "bengal",       # catches Bengal AND Bengali (bangladesh handles Bangladeshi orgs)

    # No clean geographic root — keep the community term as-is
    "sikh",
    "tamil",
    "telugu",
    "marathi",
    "odia",
    "orissa",       # older spelling still in legacy org names
]

# Classification taxonomy — matches your Supabase tags
COMMUNITIES = [
    "Pan-South Asian", "Indian American", "Pakistani American",
    "Bangladeshi American", "Sri Lankan American", "Nepali American",
    "Tamil", "Telugu", "Gujarati", "Punjabi", "Bengali", "Malayali",
    "Kannada", "Marathi", "Odia", "Sindhi", "Kashmiri",
    "Sikh", "Hindu", "Muslim", "Tibetan-American",
]

SERVICES = [
    "Advocacy & Civic Engagement", "Arts & Culture", "Business & Professional",
    "Community Building", "Education", "Health & Wellness", "Legal Aid",
    "Media & Communications", "Religious & Spiritual", "Social Services",
    "Sports & Recreation", "Women & Gender", "Youth & Students",
    "Immigration & Refugee Services", "LGBTQ+",
]

SCOPES = ["National", "Regional / State", "Metropolitan / Local"]

# ── ProPublica API ─────────────────────────────────────────────────────────────

PP_SEARCH = "https://projects.propublica.org/nonprofits/api/v2/search.json"
PP_ORG    = "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"
PP_HEADERS = {"User-Agent": "Banyan-Directory/1.0 (nonprofit research; contact@banyan.community)"}


def pp_search(query: str, page: int = 0) -> list[dict]:
    """One page of ProPublica search results (25 orgs per page)."""
    try:
        resp = requests.get(
            PP_SEARCH,
            params={"q": query, "page": page},
            headers=PP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("organizations", [])
    except Exception as e:
        log.warning(f"ProPublica search failed (q={query!r} p={page}): {e}")
        return []


def pp_org_detail(ein: str) -> dict:
    """Fetch full org record from ProPublica, including website URL."""
    try:
        resp = requests.get(
            PP_ORG.format(ein=ein),
            headers=PP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("organization", {})
    except Exception as e:
        log.debug(f"PP org detail failed (ein={ein}): {e}")
        return {}


def discover_candidates(queries: list[str], state_filter: Optional[str] = None,
                         max_pages: int = 4) -> list[dict]:
    """
    Search ProPublica for all query terms, deduplicate by EIN,
    optionally filter to one state. Returns raw ProPublica records.
    """
    seen_eins: set[str] = set()
    candidates: list[dict] = []

    for query in queries:
        log.info(f"  Searching ProPublica: {query!r}")
        for page in range(max_pages):
            results = pp_search(query, page)
            if not results:
                break
            for org in results:
                ein = str(org.get("ein", "")).strip()
                st  = org.get("state", "")
                if not ein or ein in seen_eins:
                    continue
                if state_filter and st != state_filter:
                    continue
                seen_eins.add(ein)
                candidates.append(org)
            time.sleep(0.4)  # polite rate limit

    log.info(f"  {len(candidates)} unique candidates found across {len(queries)} queries")
    return candidates


# ── Supabase helpers ───────────────────────────────────────────────────────────

def sb_get(sb_url: str, sb_key: str, path: str, params: dict | None = None) -> list[dict]:
    headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Accept":        "application/json",
    }
    resp = requests.get(
        f"{sb_url.rstrip('/')}/rest/v1/{path}",
        headers=headers, params=params, timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def sb_insert(sb_url: str, sb_key: str, table: str, data: dict) -> None:
    headers = {
        "apikey":        sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }
    resp = requests.post(
        f"{sb_url.rstrip('/')}/rest/v1/{table}",
        headers=headers, json=data, timeout=20,
    )
    resp.raise_for_status()


def load_existing(sb_url: str, sb_key: str) -> tuple[set[str], set[str]]:
    """
    Returns (existing_names_normalized, existing_websites) so we can
    skip orgs already in the directory or already submitted for review.
    """
    names: set[str] = set()
    urls:  set[str] = set()

    # Confirmed orgs
    orgs = sb_get(sb_url, sb_key, "organizations",
                  {"select": "name,website_url", "limit": "5000"})
    for o in orgs:
        if o.get("name"):
            names.add(_norm(o["name"]))
        if o.get("website_url"):
            urls.add(_norm_url(o["website_url"]))

    # Already-pending auto-discoveries
    subs = sb_get(sb_url, sb_key, "pending_submissions",
                  {"select": "name,website_url",
                   "submitter_notes": "like.Auto-discovered%",
                   "limit": "2000"})
    for s in subs:
        if s.get("name"):
            names.add(_norm(s["name"]))
        if s.get("website_url"):
            urls.add(_norm_url(s["website_url"]))

    log.info(f"  {len(names)} existing org names loaded for dedup")
    return names, urls


def _norm(s: str) -> str:
    """
    Normalize an org name for dedup comparison:
      1. Strip leading 'The'
      2. Lowercase and remove punctuation
      3. Strip trailing legal entity suffixes (Inc, LLC, Ltd, etc.)
         that 990 filings append but directories often omit.
    """
    s = s.strip()
    # Remove leading "The"
    s = re.sub(r"^the\s+", "", s, flags=re.IGNORECASE)
    # Lowercase and remove punctuation (handles "Inc." → "inc", "L.L.C." → "llc")
    s = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    # Strip trailing legal entity designators — these carry no semantic meaning
    s = re.sub(
        r"\s+(inc|incorporated|llc|ltd|limited|corp|corporation|lp|llp|pllc)\s*$",
        "", s
    ).strip()
    return s


def _norm_url(u: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", u.lower()).rstrip("/")


# ── Website scraping ───────────────────────────────────────────────────────────

def fetch_website_text(url: str, max_chars: int = 3000) -> str:
    """Fetch homepage and return clean text excerpt for classification."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BanyanBot/1.0)"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove boilerplate tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        return text[:max_chars]
    except Exception as e:
        log.debug(f"  Website fetch failed ({url}): {e}")
        return ""


# ── Claude classification ──────────────────────────────────────────────────────

CLASSIFY_PROMPT = """\
You are a research assistant helping build a directory of South Asian American (SAA) organizations in the United States.

Classify the nonprofit below. Respond ONLY with a valid JSON object — no markdown, no explanation.

Organization name: {name}
City/State: {city}, {state}
{description_line}
{website_line}

JSON schema:
{{
  "is_saa_org": true or false,
  "confidence": float 0.0–1.0,
  "communities_served": array, choose from: {communities},
  "services": array, choose from: {services},
  "scope_of_service": one of: {scopes},
  "description": "1–2 sentence description of the org (write one if not provided)",
  "reasoning": "1 sentence explaining your classification decision"
}}

Rules:
- is_saa_org = true if South Asian identity defines WHO the organization is for — regardless of how narrow or specialized its mission is.
  This includes: cultural and community orgs, professional associations for South Asian practitioners,
  health/disease groups specifically for South Asians, religious organizations, student groups,
  business networks, arts organizations, and advocacy groups — as long as South Asian identity
  is core to who belongs or who is served.
  Ask yourself: "Is this org for South Asian people?" If yes, it counts.
- is_saa_org = false only if South Asian appears incidentally — e.g. a general hospital that
  happens to mention South Asian patients in passing, a university South Asian Studies department
  (serves scholars of the topic, not the community), or a purely commercial entity.
- Do NOT penalize narrow focus. A South Asian cardiology association serves South Asian
  cardiologists and belongs in the directory. A South Asian diabetes foundation creates
  culturally safe space for South Asians and belongs in the directory.
- Universities, academic area-studies programs, restaurants, and purely commercial entities → is_saa_org = false
- If the org's focus is unclear from the name alone but the website confirms SAA identity → is_saa_org = true
- confidence should reflect how certain you are, not how good the org is
- communities_served and services: pick all that clearly apply, empty array if none fit
"""


def classify_org(client: Anthropic, name: str, city: str, state: str,
                 description: str, website_text: str) -> dict | None:
    """Call Claude Haiku to classify an org. Returns parsed JSON or None on error."""
    desc_line = f"990 description: {description}" if description else ""
    web_line  = f"Website excerpt: {website_text[:2000]}" if website_text else ""

    prompt = CLASSIFY_PROMPT.format(
        name=name, city=city, state=state,
        description_line=desc_line,
        website_line=web_line,
        communities=json.dumps(COMMUNITIES),
        services=json.dumps(SERVICES),
        scopes=json.dumps(SCOPES),
    )

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip any accidental markdown fencing
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.MULTILINE)
        return json.loads(raw)
    except Exception as e:
        log.warning(f"  Classification failed ({name}): {e}")
        return None


# ── Main pipeline ──────────────────────────────────────────────────────────────

def _setup_logging() -> Path:
    """
    Configure logging to both the console and a timestamped file.
    Log files are written to pipeline/logs/ and named by run datetime.
    Returns the path to the log file so it can be reported at the end.
    """
    import datetime
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"discovery_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    fmt = logging.Formatter("%(levelname)s  %(message)s")

    # Console handler — shows live output while running
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    # File handler — persists the full run log
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(fh)

    return log_file


def run(
    queries:        list[str]     = DEFAULT_QUERIES,
    state_filter:   Optional[str] = None,
    limit:          Optional[int] = None,
    min_confidence: float         = 0.80,
    write:          bool          = False,
) -> None:
    log_file = _setup_logging()
    log.info(f"Log file: {log_file}")

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not sb_url or not sb_key:
        log.error("Set SUPABASE_URL and SUPABASE_KEY env vars.")
        sys.exit(1)
    if not api_key:
        log.error("Set ANTHROPIC_API_KEY env var.")
        sys.exit(1)

    if not write:
        log.info("=== DRY RUN — no data will be written. Pass --write to insert. ===\n")

    client = Anthropic(api_key=api_key)

    # 1. Load existing orgs for dedup
    log.info("Loading existing orgs from Supabase…")
    existing_names, existing_urls = load_existing(sb_url, sb_key)

    # 2. Discover candidates from ProPublica
    log.info("\nSearching ProPublica Nonprofit Explorer…")
    candidates = discover_candidates(queries, state_filter)
    if limit:
        candidates = candidates[:limit]
        log.info(f"  Capped to {limit} candidates")

    # 3. Process each candidate
    stats = {"processed": 0, "skipped_dup": 0, "skipped_not_saa": 0,
             "skipped_low_conf": 0, "inserted": 0, "errors": 0}

    log.info(f"\nProcessing {len(candidates)} candidates…\n")

    for i, cand in enumerate(candidates, 1):
        ein       = str(cand.get("ein", "")).strip()
        name      = (cand.get("name") or "").strip()
        city      = (cand.get("city") or "").strip()
        state     = (cand.get("state") or "").strip()
        ntee_code = (cand.get("ntee_code") or "")

        if not name:
            continue

        log.info(f"[{i}/{len(candidates)}] {name} ({city}, {state})")

        # Dedup by name
        if _norm(name) in existing_names:
            log.info("  → Skip: already in directory")
            stats["skipped_dup"] += 1
            continue

        # Fetch full detail (website URL) from ProPublica
        detail  = pp_org_detail(ein) if ein else {}
        website = (detail.get("website") or "").strip()
        desc_raw = ""  # ProPublica rarely has a description, but check anyway

        # Dedup by website URL
        if website and _norm_url(website) in existing_urls:
            log.info("  → Skip: website already in directory")
            stats["skipped_dup"] += 1
            continue

        # Fetch website text for richer classification
        website_text = ""
        if website:
            log.info(f"  Fetching website: {website}")
            website_text = fetch_website_text(website)
            time.sleep(0.3)

        # Classify with Claude
        log.info("  Classifying with Claude…")
        result = classify_org(client, name, city, state, desc_raw, website_text)
        time.sleep(0.2)  # gentle rate limit

        if result is None:
            stats["errors"] += 1
            continue

        stats["processed"] += 1
        is_saa    = result.get("is_saa_org", False)
        confidence = float(result.get("confidence", 0))
        reasoning = result.get("reasoning", "")

        log.info(f"  is_saa={is_saa}  confidence={confidence:.2f}  — {reasoning}")

        if not is_saa:
            log.info("  → Skip: not an SAA org")
            stats["skipped_not_saa"] += 1
            continue

        if confidence < min_confidence:
            log.info(f"  → Skip: confidence {confidence:.2f} < {min_confidence}")
            stats["skipped_low_conf"] += 1
            continue

        # Build submission record
        submission = {
            "submission_type": "new_org",
            "name":             name,
            "state":            state or None,
            "description":      result.get("description") or None,
            "website_url":      website or None,
            "scope_of_service": result.get("scope_of_service") or None,
            "services":         result.get("services") or [],
            "communities_served": result.get("communities_served") or [],
            "submitter_name":   "Banyan Discovery Bot",
            "submitter_email":  "discovery@banyan.community",
            "submitter_notes":  (
                f"Auto-discovered via ProPublica 990 | "
                f"EIN: {ein} | "
                f"NTEE: {ntee_code} | "
                f"Confidence: {confidence:.2f} | "
                f"Reasoning: {reasoning}"
            ),
        }

        log.info(f"  ✓ Candidate: {name} — {result.get('scope_of_service')} | "
                 f"services: {result.get('services')} | "
                 f"communities: {result.get('communities_served')}")

        if write:
            try:
                sb_insert(sb_url, sb_key, "pending_submissions", submission)
                existing_names.add(_norm(name))
                if website:
                    existing_urls.add(_norm_url(website))
                stats["inserted"] += 1
                log.info("  → Inserted to pending_submissions")
            except Exception as e:
                log.warning(f"  → Insert failed: {e}")
                stats["errors"] += 1
        else:
            stats["inserted"] += 1  # count as "would insert" in dry run
            log.info("  → Would insert (dry run)")

    # 4. Summary
    mode = "INSERTED" if write else "WOULD INSERT"
    log.info(f"""
{'='*60}
Discovery run complete
  Candidates found:      {len(candidates)}
  Processed:             {stats['processed']}
  Skipped (duplicate):   {stats['skipped_dup']}
  Skipped (not SAA):     {stats['skipped_not_saa']}
  Skipped (low conf):    {stats['skipped_low_conf']}
  Errors:                {stats['errors']}
  {mode}:              {stats['inserted']}
{'='*60}
""")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover SAA orgs via ProPublica + Claude")
    parser.add_argument("--write",          action="store_true",  help="Write to Supabase (default: dry run)")
    parser.add_argument("--state",          type=str,             help="Filter to one state (e.g. CA)")
    parser.add_argument("--limit",          type=int,             help="Max candidates to process")
    parser.add_argument("--query",          type=str,             help="Single search term (overrides defaults)")
    parser.add_argument("--min-confidence", type=float, default=0.80, help="Min confidence to include (default 0.80)")
    args = parser.parse_args()

    queries = [args.query] if args.query else DEFAULT_QUERIES

    run(
        queries=queries,
        state_filter=args.state,
        limit=args.limit,
        min_confidence=args.min_confidence,
        write=args.write,
    )
