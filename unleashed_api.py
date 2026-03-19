from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.unleashedsoftware.com"


def _get_signature(query_string: str, api_key: str) -> str:
    """Generate HMAC-SHA256 signature for the Unleashed API."""
    key = api_key.encode("utf-8")
    message = query_string.encode("utf-8")
    signature = hmac.HMAC(key, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")


def _make_request(endpoint: str, params: dict, api_id: str, api_key: str) -> dict:
    """Make an authenticated GET request to the Unleashed API."""
    query_string = urlencode(params) if params else ""
    signature = _get_signature(query_string, api_key)

    url = f"{BASE_URL}/{endpoint}"
    if query_string:
        url += f"?{query_string}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "api-auth-id": api_id,
        "api-auth-signature": signature,
        "client-type": "bosh/po-automation",
    }

    logger.info("GET %s", url)
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def _parse_date(date_str: str) -> str:
    """Parse Unleashed date format (/Date(ms)/) to YYYY-MM-DD."""
    if not date_str:
        return ""
    if "/Date(" in date_str:
        ms = int(re.search(r"/Date\((\d+)\)/", date_str).group(1))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return date_str


def fetch_sales_orders(config: dict) -> list:
    """Fetch all sales orders from Unleashed."""
    api_cfg = config["unleashed"]
    data = _make_request("SalesOrders", {}, api_cfg["api_id"], api_cfg["api_key"])
    orders = data.get("Items", [])
    logger.info("Fetched %d sales orders", len(orders))
    return orders


def find_matching_order(orders: list, config: dict) -> dict | None:
    """Find the next upcoming Sales Order for the configured customer and depot.

    Matches on customer name and delivery name/city containing the depot name.
    Returns the Placed order with the nearest future required date.
    """
    search = config["search"]
    customer_name = search["customer_name"].lower()
    depot_name = search["depot_name"].lower()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    matching = []
    for so in orders:
        # Must be Placed (not Completed or Parked)
        if so.get("OrderStatus") != "Placed":
            continue

        # Check customer
        customer = so.get("Customer", {})
        cust_name = (customer.get("CustomerName") or "").lower()
        if customer_name not in cust_name:
            continue

        # Check depot in delivery name or city
        delivery_name = (so.get("DeliveryName") or "").lower()
        delivery_city = (so.get("DeliveryCity") or "").lower()
        if depot_name not in delivery_name and depot_name not in delivery_city:
            continue

        required_date = _parse_date(so.get("RequiredDate") or "")
        if required_date and required_date >= today:
            matching.append((required_date, so))
            logger.info(
                "Matched SO %s — Customer: %s, Depot: %s, RequiredDate: %s",
                so.get("OrderNumber"), cust_name, delivery_name, required_date,
            )

    if not matching:
        logger.warning("No sales orders matched customer=%s depot=%s", customer_name, depot_name)
        return None

    # Return the one with the nearest future required date
    matching.sort(key=lambda x: x[0])
    chosen_date, chosen_so = matching[0]
    logger.info("Selected SO %s with RequiredDate %s", chosen_so.get("OrderNumber"), chosen_date)
    return chosen_so


def get_order_details(so: dict) -> tuple:
    """Extract required date and product quantities from a Sales Order.

    Returns (required_date_str, {product_code: quantity}).
    """
    required_date = _parse_date(so.get("RequiredDate") or "")

    lines = so.get("SalesOrderLines", [])
    quantities = {}
    for line in lines:
        product = line.get("Product", {})
        code = product.get("ProductCode", "")
        qty = int(line.get("OrderQuantity", 0))
        quantities[code] = qty
        logger.info("  %s: %d", code, qty)

    logger.info("SO %s — RequiredDate: %s, %d line items", so.get("OrderNumber"), required_date, len(quantities))
    return required_date, quantities
