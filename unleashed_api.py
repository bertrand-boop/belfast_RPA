from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import re
from datetime import datetime, timedelta, timezone
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
    """Find the Sales Order for the configured customer and depot with delivery in 3 days.

    Matches on customer name and delivery name/city containing the depot name.
    Returns the order with required date = today + 3 days.
    """
    search = config["search"]
    customer_name = search["customer_name"].lower()
    depot_name = search["depot_name"].lower()
    warehouse_code = search["warehouse_code"]

    target_date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    logger.info("Looking for orders with RequiredDate = %s (today + 3 days)", target_date)

    for so in orders:
        # Must be Placed (not Completed or Parked)
        if so.get("OrderStatus") != "Placed":
            continue

        # Check warehouse (Turners = W6)
        warehouse = so.get("Warehouse", {})
        if (warehouse.get("WarehouseCode") or "") != warehouse_code:
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
        if required_date == target_date:
            logger.info(
                "Matched SO %s — Warehouse: %s, Customer: %s, Depot: %s, RequiredDate: %s",
                so.get("OrderNumber"), warehouse.get("WarehouseName"),
                cust_name, delivery_name, required_date,
            )
            return so

    logger.warning("No sales order matched warehouse=%s customer=%s depot=%s date=%s",
                   warehouse_code, customer_name, depot_name, target_date)
    return None


def get_order_details(so: dict, config: dict) -> tuple:
    """Extract required date and product quantities from a Sales Order.

    Filters line items to only those whose ProductCode appears in
    config['search']['product_codes']. If product_codes is missing or empty,
    all line items are returned (preserving previous behaviour).
    Returns (required_date_str, {product_code: quantity}).
    """
    required_date = _parse_date(so.get("RequiredDate") or "")
    lines = so.get("SalesOrderLines", [])

    allowed_codes = set(config.get("search", {}).get("product_codes") or [])
    if allowed_codes:
        logger.info(
            "Filtering line items to %d configured ProductCodes: %s",
            len(allowed_codes), ", ".join(sorted(allowed_codes)),
        )

    quantities = {}
    skipped = []
    for line in lines:
        product = line.get("Product", {})
        code = product.get("ProductCode", "")
        qty = int(line.get("OrderQuantity", 0))

        if allowed_codes and code not in allowed_codes:
            skipped.append(code)
            continue

        quantities[code] = qty
        logger.info("  %s: %d", code, qty)

    if skipped:
        logger.info(
            "Skipped %d line item(s) not in product_codes filter: %s",
            len(skipped), ", ".join(skipped),
        )

    # Surface any configured SKUs that weren't on the order — likely worth knowing
    missing = allowed_codes - set(quantities.keys())
    if missing:
        logger.warning(
            "Configured ProductCodes not present on SO %s: %s",
            so.get("OrderNumber"), ", ".join(sorted(missing)),
        )

    logger.info(
        "SO %s — RequiredDate: %s, %d matched line items",
        so.get("OrderNumber"), required_date, len(quantities),
    )
    return required_date, quantities
