"""Account selection and durable per-account deadlines. No cookies are stored here."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from tradesea_lockout import ROOT, DURATIONS, StateStore


def identity(account):
    return {"externalAccountId": str(account["externalAccountId"]),
            "accountType": account["accountType"], "propFirm": account.get("propFirm", "")}


def account_key(account):
    return json.dumps(identity(account), sort_keys=True, separators=(",", ":"))


def label(account):
    return str(account.get("name") or account.get("accountName") or account["externalAccountId"])


def is_lucid(account):
    return account.get("propFirm") == "LucidTrading" and account.get("type") in ("live", "locked")


def defaults():
    return {"version": 1, "mode": "all-lucid", "durationSeconds": 43200, "accounts": []}


def validate_settings(value):
    if not isinstance(value, dict) or value.get("version") not in (1, 2) or value.get("mode") not in ("all-lucid", "selected"):
        raise ValueError("Saved account settings are invalid. They have not been reset.")
    if type(value.get("durationSeconds")) is not int or value["durationSeconds"] not in DURATIONS:
        raise ValueError("Saved duration is invalid. Choose a supported duration in the panel.")
    refs = value.get("accounts")
    if not isinstance(refs, list):
        raise ValueError("Saved account selection is invalid.")
    keys = set()
    for ref in refs:
        if not isinstance(ref, dict) or any(not isinstance(ref.get(k), str) or not ref[k] for k in ("externalAccountId", "accountType")):
            raise ValueError("Saved account identity is invalid.")
        if not isinstance(ref.get("propFirm"), str) or account_key(ref) in keys:
            raise ValueError("Saved account selection is ambiguous.")
        keys.add(account_key(ref))
        if value["version"] == 2 and ref.get("category") not in ("asia", "day"):
            raise ValueError("Choose a valid account category.")
    if value["version"] == 2 and value["mode"] != "selected":
        raise ValueError("Category settings require explicit allocation.")
    if value["version"] == 1 and value["mode"] == "selected" and not refs:
        raise ValueError("Choose at least one account.")
    return value


def account_duration(settings, account):
    if settings["version"] == 2:
        ref = next((a for a in settings["accounts"] if account_key(a) == account_key(account)), None)
        if ref and ref["category"] == "day":
            return 86400
    return settings["durationSeconds"]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Repository:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.settings_path = self.root / ".asia-settings.json"
        self.states = self.root / ".asia-lockouts"

    def settings(self):
        if not self.settings_path.exists():
            return defaults()
        try:
            return deepcopy(validate_settings(json.loads(self.settings_path.read_text(encoding="utf-8"))))
        except (ValueError, OSError) as exc:
            raise RuntimeError("Saved Asia settings could not be read. They have not been reset.") from exc

    def save_settings(self, value):
        atomic_json(self.settings_path, validate_settings(value))

    def store(self, account):
        self.states.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(account_key(account).encode("utf-8")).hexdigest()
        return StateStore(self.states / (digest + ".json"))

    def migrate(self):
        legacy = StateStore(self.root / ".asia-lockout.json").load()
        if legacy:
            store = self.store({**legacy["account"], "propFirm": "LucidTrading"})
            saved = store.load()
            if saved is None:
                store.save(legacy)
            elif not legacy["cycle"]["finished"] and legacy["cycle"]["end"] > saved["cycle"]["end"]:
                raise RuntimeError("Saved Asia deadlines disagree. No existing lockout has been replaced.")

    def last_run(self):
        path = self.root / ".asia-last-run.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None


def resolve_accounts(settings, accounts):
    keys = [account_key(a) for a in accounts]
    if len(keys) != len(set(keys)):
        raise RuntimeError("TradeSea returned ambiguous account identities. Refresh before continuing.")
    if settings["mode"] == "all-lucid":
        selected = [a for a in accounts if is_lucid(a)]
        return selected, []
    by_key = dict(zip(keys, accounts))
    selected, missing = [], []
    for reference in settings["accounts"]:
        account = by_key.get(account_key(reference))
        if account:
            selected.append(account)
        else:
            missing.append(reference)
    return selected, missing
