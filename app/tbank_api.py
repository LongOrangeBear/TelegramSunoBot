"""T-Bank (Tinkoff) Acquiring API client.

Docs: https://developer.tbank.ru/eacq/api
"""

import hashlib
import logging
from typing import Any

import aiohttp

from app.config import config

logger = logging.getLogger(__name__)

TBANK_API_URL = "https://securepay.tinkoff.ru/v2"

# Fields excluded from token generation (nested objects/arrays)
_TOKEN_EXCLUDE_KEYS = {"Token", "DATA", "Receipt", "Data"}

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


def generate_token(params: dict[str, Any]) -> str:
    """Generate SHA-256 token for T-Bank API request.

    Algorithm (from official docs):
    1. Collect root-level scalar params as key:value pairs
    2. Add Password
    3. Sort alphabetically by key
    4. Concatenate values
    5. SHA-256 hash
    """
    # Collect only scalar (non-dict, non-list) values, excluding Token itself
    token_pairs: dict[str, str] = {}
    for key, value in params.items():
        if key in _TOKEN_EXCLUDE_KEYS:
            continue
        if isinstance(value, (dict, list)):
            continue
        # Convert booleans to lowercase strings as T-Bank expects
        if isinstance(value, bool):
            token_pairs[key] = str(value).lower()
        else:
            token_pairs[key] = str(value)

    # Add password
    token_pairs["Password"] = config.tbank_password

    # Sort by key, concatenate values
    sorted_keys = sorted(token_pairs.keys())
    concat = "".join(token_pairs[k] for k in sorted_keys)

    # SHA-256
    return hashlib.sha256(concat.encode("utf-8")).hexdigest()


def verify_notification_token(data: dict[str, Any]) -> bool:
    """Verify the Token in an incoming notification from T-Bank.

    Same algorithm as generate_token but applied to notification params.
    """
    received_token = data.get("Token", "")
    if not received_token:
        return False

    # Build pairs from all params except Token and nested objects
    token_pairs: dict[str, str] = {}
    for key, value in data.items():
        if key in _TOKEN_EXCLUDE_KEYS:
            continue
        if isinstance(value, (dict, list)):
            continue
        if isinstance(value, bool):
            token_pairs[key] = str(value).lower()
        else:
            token_pairs[key] = str(value)

    token_pairs["Password"] = config.tbank_password

    sorted_keys = sorted(token_pairs.keys())
    concat = "".join(token_pairs[k] for k in sorted_keys)
    expected_token = hashlib.sha256(concat.encode("utf-8")).hexdigest()

    return expected_token == received_token


async def init_payment(
    amount_rub: int,
    order_id: str,
    description: str,
    notification_url: str | None = None,
) -> dict[str, Any]:
    """Initialize a payment via T-Bank API.

    Args:
        amount_rub: Amount in rubles (will be converted to kopecks).
        order_id: Unique order ID.
        description: Order description (shown on payment form, max 140 chars).
        notification_url: Optional webhook URL for payment notifications.

    Returns:
        Dict with PaymentId, PaymentURL, etc.
    """
    amount_kopecks = amount_rub * 100

    payload = {
        "TerminalKey": config.tbank_terminal_key,
        "Amount": amount_kopecks,
        "OrderId": order_id,
        "Description": description[:140],
        "PayType": "O",  # one-stage payment
        "Language": "ru",
    }

    if notification_url:
        payload["NotificationURL"] = notification_url

    # Generate and add token
    payload["Token"] = generate_token(payload)

    session = await _get_session()
    async with session.post(
        f"{TBANK_API_URL}/Init",
        json=payload,
        headers={"Content-Type": "application/json"},
    ) as resp:
        result = await resp.json()
        logger.info(f"T-Bank Init response: Success={result.get('Success')}, "
                     f"PaymentId={result.get('PaymentId')}, "
                     f"ErrorCode={result.get('ErrorCode')}")
        return result


async def get_payment_state(payment_id: str) -> dict[str, Any]:
    """Get the current state of a payment."""
    payload = {
        "TerminalKey": config.tbank_terminal_key,
        "PaymentId": payment_id,
    }
    payload["Token"] = generate_token(payload)

    session = await _get_session()
    async with session.post(
        f"{TBANK_API_URL}/GetState",
        json=payload,
        headers={"Content-Type": "application/json"},
    ) as resp:
        return await resp.json()
