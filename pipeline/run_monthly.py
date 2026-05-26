"""
SAA Org Health Tracker — Monthly Orchestrator
Runs website monitoring and social media collection.
Called by GitHub Actions on the 1st of each month.
"""

import logging
import sys
import time

import website_monitor
import social_crawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


def main():
    start = time.time()
    log.info("=== Monthly Pipeline Starting ===")

    log.info("--- Step 1: Website Monitor ---")
    try:
        ws_summary = website_monitor.run(dry_run=DRY_RUN)
        log.info(f"    Website: {ws_summary}")
    except Exception as e:
        log.error(f"Website monitor failed: {e}", exc_info=True)

    log.info("--- Step 2: Social Crawler ---")
    try:
        sc_summary = social_crawler.run(dry_run=DRY_RUN)
        log.info(f"    Social: {sc_summary}")
    except Exception as e:
        log.error(f"Social crawler failed: {e}", exc_info=True)

    elapsed = round(time.time() - start, 1)
    log.info(f"=== Monthly Pipeline Complete in {elapsed}s ===")


if __name__ == "__main__":
    main()
