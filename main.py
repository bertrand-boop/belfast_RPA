import argparse
import logging
import os
import sys
from datetime import datetime

import yaml

from unleashed_api import fetch_sales_orders, find_matching_order, get_order_details
from excel_builder import build_excel
from emailer import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    # Override secrets from environment variables (for GitHub Actions)
    env_overrides = {
        "UNLEASHED_API_ID": ("unleashed", "api_id"),
        "UNLEASHED_API_KEY": ("unleashed", "api_key"),
        "EMAIL_SENDER": ("email", "sender"),
        "EMAIL_APP_PASSWORD": ("email", "app_password"),
    }
    for env_var, (section, key) in env_overrides.items():
        value = os.environ.get(env_var)
        if value:
            config[section][key] = value

    return config


def run_job():
    """Execute the full pipeline: fetch PO → populate Excel → email."""
    logger.info("=== Job started at %s ===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    excel_path = None
    try:
        config = load_config()

        # Step 1: Fetch sales orders from Unleashed
        orders = fetch_sales_orders(config)

        # Step 2: Find the matching order (Tesco Belfast)
        so = find_matching_order(orders, config)
        if so is None:
            logger.error("No matching sales order found — aborting")
            return

        # Step 3: Extract data from order (filtered to configured ProductCodes)
        required_date, quantities = get_order_details(so, config)

        # Step 4: Build Excel from template
        excel_path = build_excel(required_date, quantities)

        # Step 5: Send email
        send_email(excel_path, required_date, config)

        logger.info("=== Job completed successfully ===")
    except Exception:
        logger.exception("Job failed")
    finally:
        if excel_path and os.path.exists(excel_path):
            os.remove(excel_path)
            logger.info("Cleaned up %s", excel_path)


def main():
    parser = argparse.ArgumentParser(description="Unleashed PO → Excel → Email Automation")
    parser.add_argument("--now", action="store_true", help="Run the job immediately")
    args = parser.parse_args()

    if args.now:
        logger.info("Running job immediately (--now flag)")
        run_job()
    else:
        logger.info("Use --now to run, or trigger via GitHub Actions")


if __name__ == "__main__":
    main()
