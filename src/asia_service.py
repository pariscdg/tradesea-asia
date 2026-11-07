"""Read-only panel operations and one scheduled lockout run."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging

from asia_settings import Repository, account_key, account_duration, atomic_json, identity, label, resolve_accounts, validate_settings
from tradesea_auth import TradeSeaSession, get_accounts, get_tradesea_cookie
from tradesea_lockout import AsiaProtection, LockoutApi, single_instance


def session_for(token, account):
    return TradeSeaSession(token, "", account["id"], str(account["externalAccountId"]), account["accountType"])


class AsiaService:
    def __init__(self, repository=None, authenticate=get_tradesea_cookie, accounts=get_accounts, api_factory=LockoutApi):
        self.repo = repository or Repository()
        self.authenticate, self.accounts, self.api_factory = authenticate, accounts, api_factory

    def mutex(self):
        return single_instance(self.repo.root / ".asia-lockout.mutex")

    def connect(self, interactive=False):
        token = self.authenticate(headless=not interactive, timeout_seconds=180 if interactive else 45)
        accounts = self.accounts(token)
        # Detect identity collisions even before the user makes a selection.
        resolve_accounts(self.repo.settings(), accounts)
        return token, accounts

    def status(self, token, account):
        saved = self.repo.store(account).load()
        try:
            remote, now = self.api_factory(session_for(token, account)).get()
            if saved and now < saved["serverFloor"]:
                raise RuntimeError("TradeSea server time moved backwards.")
            local = saved and not saved["cycle"]["finished"] and (
                saved["cycle"]["end"] > now or not saved["cycle"]["confirmed"])
            active = remote and remote["end"] > now
            locked = bool(local or active or account.get("type") == "locked")
            end = max(saved["cycle"]["end"] if local else 0, remote["end"] if active else 0) or None
            return {"locked": locked, "end": end, "verified": True, "error": None}
        except Exception:
            return {"locked": True, "end": saved["cycle"]["end"] if saved else None,
                    "verified": False, "error": "Lockout status unavailable"}

    def inspect(self, token, accounts):
        with ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(lambda account: self.status(token, account), accounts))
        return {account_key(account): status for account, status in zip(accounts, statuses)}

    def load(self, interactive=False):
        with self.mutex():
            self.repo.migrate()
            token, accounts = self.connect(interactive)
            return {"accounts": accounts, "settings": self.repo.settings(), "statuses": self.inspect(token, accounts),
                    "lastRun": self.repo.last_run()}

    def save(self, settings):
        validate_settings(settings)
        with self.mutex():
            self.repo.migrate()
            previous = self.repo.settings()
            token, accounts = self.connect()
            selected, missing = resolve_accounts(settings, accounts)
            if missing or (not selected and settings["version"] == 1):
                raise RuntimeError("A selected account is unavailable. Refresh the list and choose available accounts.")
            statuses = self.inspect(token, selected)
            if any(account_duration(settings, a) != account_duration(previous, a)
                   and statuses[account_key(a)]["locked"] for a in selected):
                raise RuntimeError("Duration cannot change while a selected account is locked or its status is unavailable.")
            # Settings never write to a deadline record or send a lockout request.
            self.repo.save_settings(settings)
            return {"accounts": accounts, "settings": settings, "statuses": self.inspect(token, accounts),
                    "lastRun": self.repo.last_run()}

    def run(self):
        results = []
        try:
            with self.mutex():
                self.repo.migrate()
                settings = self.repo.settings()
                token, accounts = self.connect()
                selected, missing = resolve_accounts(settings, accounts)
                for account in missing:
                    results.append({"account": label(account), "ok": False, "message": "Account unavailable in saved login"})
                if not selected and not missing and settings["version"] == 1:
                    raise RuntimeError("No selected accounts are available in the saved login.")
                for account in selected:
                    try:
                        protection = AsiaProtection(self.repo.store(account), account_duration(settings, account))
                        api = self.api_factory(session_for(token, account))
                        status = protection.step(session_for(token, account), api)
                        if status == "finished":
                            status = protection.step(session_for(token, account), api)
                        if status not in ("confirmed", "existing"):
                            raise RuntimeError("TradeSea has not confirmed this lockout.")
                        end = protection.state["cycle"]["end"] if protection.state else None
                        results.append({"account": label(account), "ok": True, "end": end,
                                        "message": "Existing lockout retained" if status == "existing" else "Lockout confirmed"})
                    except Exception as exc:
                        results.append({"account": label(account), "ok": False, "message": str(exc)})
                report = {"at": datetime.now(timezone.utc).isoformat(), "results": results,
                          "ok": all(item["ok"] for item in results)}
                atomic_json(self.repo.root / ".asia-last-run.json", report)
                logging.info("Asia run complete: %s of %s accounts confirmed. Exiting.", sum(r["ok"] for r in results), len(results))
                return 0 if report["ok"] else 1
        except Exception as exc:
            logging.error("Asia run failed: %s", exc)
            atomic_json(self.repo.root / ".asia-last-run.json", {
                "at": datetime.now(timezone.utc).isoformat(), "ok": False, "error": str(exc), "results": results})
            return 1
