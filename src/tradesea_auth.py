"""Obtain TradeSea credentials through the site's persistent Chrome login."""

from __future__ import annotations

import base64
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests


APP_URL = "https://app.tradesea.ai/"
COOKIE_NAME = "access_token"
ACCOUNTS_URL = "https://prod-identity.tradesea.ai/eum/v1/accountsWithDetails"
LUCID_PROP_FIRM = "LucidTrading"
PROFILE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / ".tradesea-browser-profile"


@dataclass(frozen=True)
class TradeSeaSession:
    access_token: str
    websocket_url: str
    account_id: str
    external_account_id: str = ""
    account_type: str = ""


def get_accounts(access_token: str) -> list[dict]:
    try:
        response = requests.get(ACCOUNTS_URL, headers={
            "Cookie": f"{COOKIE_NAME}={access_token}", "Accept": "application/json",
            "Origin": APP_URL.rstrip("/"), "Referer": APP_URL}, timeout=20, allow_redirects=False)
    except requests.RequestException as exc:
        raise RuntimeError("TradeSea could not be reached. Try refreshing the saved login.") from exc
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"TradeSea account lookup failed (HTTP {response.status_code}).")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("TradeSea returned an invalid account list.") from exc
    if not isinstance(payload, dict) or payload.get("s") not in ("ok", "success") or not isinstance(payload.get("d"), list):
        raise RuntimeError("TradeSea returned an invalid account list.")
    return [dict(account) for account in payload["d"] if isinstance(account, dict)
            and isinstance(account.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", account["id"])
            and account.get("externalAccountId") is not None and str(account["externalAccountId"])
            and isinstance(account.get("accountType"), str) and account["accountType"]]


def _access_token_from_cookies(cookies: list[dict[str, object]]) -> str | None:
    for cookie in cookies:
        if cookie.get("name") == COOKIE_NAME and cookie.get("value"):
            return str(cookie["value"])
    return None


def _token_is_fresh(token: str, minimum_lifetime_seconds: int = 60) -> bool:
    try:
        payload_part = token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part + padding))
        return float(payload["exp"]) > time.time() + minimum_lifetime_seconds
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def get_lucid_account(access_token: str, reference: dict | None = None) -> dict:
    """Resolve the pinned Lucid account, including while it is locked."""
    response = requests.get(
        ACCOUNTS_URL,
        headers={
            "Cookie": f"{COOKIE_NAME}={access_token}",
            "Accept": "application/json, text/plain, */*",
            "Origin": APP_URL.rstrip("/"),
            "Referer": APP_URL,
        },
        timeout=20,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"TradeSea account lookup failed (HTTP {response.status_code}).")
    payload = response.json()
    accounts = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(accounts, list) or payload.get("s") not in ("ok", "success"):
        raise RuntimeError("TradeSea returned an invalid account list.")

    lucid_accounts = [
        account
        for account in accounts
        if isinstance(account, dict)
        and account.get("propFirm") == LUCID_PROP_FIRM
        and account.get("type") in ("live", "locked")
        and isinstance(account.get("id"), str)
        and account["id"]
        and account.get("externalAccountId") is not None
        and str(account["externalAccountId"])
        and isinstance(account.get("accountType"), str)
        and account["accountType"]
    ]
    if reference:
        lucid_accounts = [account for account in lucid_accounts
                          if str(account["externalAccountId"]) == reference["externalAccountId"]
                          and account["accountType"] == reference["accountType"]]
    if len(lucid_accounts) != 1:
        raise RuntimeError(
            "Expected exactly one matching Lucid Trading account, found "
            f"{len(lucid_accounts)}. The saved account has not been switched."
        )
    return lucid_accounts[0]


def get_lucid_account_id(access_token: str) -> str:
    return get_lucid_account(access_token)["id"]


def prune_browser_metrics(profile=PROFILE_DIR):
    """Discard Chrome's per-run diagnostics, never login or site storage."""
    metrics = Path(profile) / "BrowserMetrics"
    if not metrics.is_dir() or metrics.is_symlink() or metrics.is_junction():
        return
    for diagnostic in metrics.glob("*.pma"):
        if diagnostic.is_file() and not diagnostic.is_symlink():
            try:
                diagnostic.unlink()
            except OSError:
                pass  # Chrome may still be releasing a diagnostic file.


def has_saved_login():
    return any((PROFILE_DIR / relative).is_file() for relative in
               ('Default/Network/Cookies', 'Default/Cookies'))


def get_tradesea_cookie(*, headless: bool = True, timeout_seconds: int = 60) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required. Install dependencies from requirements.txt."
        ) from exc

    PROFILE_DIR.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel="chrome", headless=headless
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not start Chrome. Close any Chrome window using the dedicated "
                f"profile at {PROFILE_DIR}, then try again."
            ) from exc

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(APP_URL, wait_until="domcontentloaded")
            logging.info("Refreshing the saved TradeSea login. Sign in in Chrome if prompted.")

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                token = _access_token_from_cookies(context.cookies([APP_URL, ACCOUNTS_URL]))
                if token and _token_is_fresh(token):
                    return token
                page.wait_for_timeout(500)

            raise RuntimeError(
                "The saved TradeSea login needs attention. Click Sign in, then refresh the accounts."
            )
        finally:
            context.close()
            prune_browser_metrics()


def get_tradesea_session(
    *, headless: bool = False, timeout_seconds: int = 180, reference: dict | None = None
) -> TradeSeaSession:
    token = get_tradesea_cookie(headless=headless, timeout_seconds=timeout_seconds)
    account = get_lucid_account(token, reference)
    return TradeSeaSession(token, "", account["id"], str(account["externalAccountId"]), account["accountType"])
