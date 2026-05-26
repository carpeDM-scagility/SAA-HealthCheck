"""
SAA Org Health Tracker — Quarterly Orchestrator
Runs the full pipeline: website + social + financials + scoring.
Called by GitHub Actions on the 1st of Jan, Apr, Jul, Oct.
"""

import logging
import sys
import time

import website_monitor
import social_crawler
import financial_fetcher
import scoring_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


def main():
    start = time.time()
    log.info("=== Quarterly Pipeline Starting ===")

    log.info("--- Step 1: Website Monitor ---")
    try:
        ws = website_monitor.run(dry_run=DRY_RUN)
        log.info(f"    {ws}")
    except Exception as e:
        log.error(f"Website monitor failed: {e}", exc_info=True)

    log.info("--- Step 2: Social Crawler ---")
    try:
        sc = social_crawler.run(dry_run=DRY_RUN)
        log.info(f"    {sc}")
    except Exception as e:
        log.error(f"Social crawler failed: {e}", exc_info=True)

    log.info("--- Step 3: Financial Fetcher ---")
    try:
        ff = financial_fetcher.run(dry_run=DRY_RUN)
        log.info(f"    {ff}")
    except Exception as e:
        log.error(f"Financial fetcher failed: {e}", exc_info=True)

    log.info("--- Step 4: Scoring Engine ---")
    try:
        se = scoring_engine.run(dry_run=DRY_RUN)
        log.info(f"    {se}")
    except Exception as e:
        log.error(f"Scoring engine failed: {e}", exc_info=True)

    elapsed = round(time.time() - start, 1)
    log.info(f"=== Quarterly Pipeline Complete in {elapsed}s ===")


if __name__ == "__main__":
    main()
