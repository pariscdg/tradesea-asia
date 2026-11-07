"""Apply a scheduled Asia lockout once and preserve its original deadline."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import tempfile

import requests

from tradesea_auth import TradeSeaSession, get_tradesea_session


ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
IDENTITY_BASE_URL = "https://prod-identity.tradesea.ai"
DURATIONS = (3600, 7200, 14400, 21600, 28800, 43200, 86400)


class LoginRequired(RuntimeError):
    pass


class MissedDeadline(RuntimeError):
    pass


def valid_epoch(value):
    return type(value) is int and 0 < value < 253402300800


def validate_state(state):
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Saved Asia protection is invalid. Refusing to reset it.")
    account = state.get("account")
    if not isinstance(account, dict) or not all(isinstance(account.get(key), str) and account[key]
                                               for key in ("externalAccountId", "accountType")):
        raise ValueError("Saved Asia account identity is invalid.")
    cycle = state.get("cycle")
    duration = state.get("durationSeconds", 43200)
    if type(duration) is not int or duration not in DURATIONS:
        raise ValueError("Saved Asia duration is invalid. Refusing to reset it.")
    if (not isinstance(cycle, dict) or not valid_epoch(cycle.get("start")) or not valid_epoch(cycle.get("end"))
            or cycle["end"] <= cycle["start"]
            or cycle.get("source", "scheduled") not in ("scheduled", "existing")
            or (cycle.get("source") != "existing" and cycle["end"] - cycle["start"] < duration)
            or type(cycle.get("confirmed")) is not bool or type(cycle.get("finished")) is not bool
            or (cycle["finished"] and not cycle["confirmed"])
            or not valid_epoch(state.get("serverFloor"))):
        minimum = "twelve hours" if duration == 43200 else "its original duration"
        raise ValueError(f"Saved Asia deadline is invalid or shorter than {minimum}. Refusing to reset it.")
    return state


class StateStore:
    def __init__(self, path=ROOT / ".asia-lockout.json"):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            return validate_state(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            raise RuntimeError("Saved Asia protection cannot be read. No replacement deadline was created.") from exc

    def save(self, state):
        validate_state(state)
        # Flush the record before replacing it; never send a PUT until the
        # original deadline is durable.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name + ".", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(state, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


@contextmanager
def single_instance(path=ROOT / ".asia-lockout.mutex"):
    import msvcrt
    with open(path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("An Asia lockout request is already running; its existing deadline is unchanged.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def read_server_lock(body):
    if not isinstance(body, dict) or body.get("status") not in ("ok", "success") or not isinstance(body.get("data"), dict):
        raise RuntimeError("TradeSea did not provide a recognized lockout response.")
    data = body["data"]
    start, end = data.get("lockoutStartTimeEpoch"), data.get("lockoutEndTimeEpoch")
    if (start is None or type(start) is int and start == 0) and (end is None or type(end) is int and end == 0):
        return None
    if not valid_epoch(start) or not valid_epoch(end) or end <= start:
        raise RuntimeError("TradeSea returned invalid lockout times.")
    return {"start": start, "end": end}


class LockoutApi:
    def __init__(self, session: TradeSeaSession, transport=requests):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", session.account_id):
            raise ValueError("TradeSea account identifier is invalid.")
        self.transport = transport
        self.url = f"{IDENTITY_BASE_URL}/eum/v1/prop-fund/{session.account_id}/lockout"
        self.headers = {"Cookie": f"access_token={session.access_token}", "Content-Type": "application/json",
                        "Accept": "application/json", "Origin": "https://app.tradesea.ai",
                        "Referer": "https://app.tradesea.ai/", "Cache-Control": "no-cache"}

    def request(self, method, payload=None):
        try:
            response = self.transport.request(method, self.url, headers=self.headers, timeout=20,
                                              allow_redirects=False, **({"json": payload} if payload else {}))
        except requests.RequestException as exc:
            raise RuntimeError("TradeSea could not be reached. The saved deadline is unchanged.") from exc
        if response.status_code in (401, 403):
            raise LoginRequired("TradeSea login or account access needs attention.")
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"TradeSea lockout request failed (HTTP {response.status_code}).")
        try:
            date = parsedate_to_datetime(response.headers["Date"])
            if date.tzinfo is None:
                raise ValueError("Missing time zone")
            now = int(date.timestamp())
            body = response.json()
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("TradeSea server time or response is invalid. Lockout is not confirmed.") from exc
        if not valid_epoch(now):
            raise RuntimeError("TradeSea server time is invalid.")
        return body, now

    def get(self):
        body, now = self.request("GET")
        return read_server_lock(body), now

    def put(self, cycle):
        minimum = 1 if cycle.get("source") == "existing" else min(DURATIONS)
        if not valid_epoch(cycle.get("start")) or not valid_epoch(cycle.get("end")) or cycle["end"] - cycle["start"] < minimum:
            raise ValueError("The Asia lockout deadline is invalid or too short.")
        body, _now = self.request("PUT", {"lockoutStartTimeEpoch": cycle["start"],
                                         "lockoutEndTimeEpoch": cycle["end"]})
        if not isinstance(body, dict) or body.get("status") not in ("ok", "success"):
            raise RuntimeError("TradeSea did not accept the lockout request.")
        # An acknowledgement alone is never confirmation.
        return self.get()


class AsiaProtection:
    def __init__(self, store, duration_seconds=43200):
        if type(duration_seconds) is not int or duration_seconds not in DURATIONS:
            raise ValueError("Choose a supported lockout duration.")
        self.duration_seconds = duration_seconds
        self.store = store
        self.state = store.load()

    @property
    def reference(self):
        return self.state["account"] if self.state else None

    def save(self):
        self.store.save(self.state)

    def check_time(self, now):
        if not valid_epoch(now) or (self.state and now < self.state["serverFloor"]):
            raise RuntimeError("TradeSea server time moved backwards. The deadline is unchanged.")

    def step(self, session, api):
        account = {"externalAccountId": session.external_account_id, "accountType": session.account_type}
        if not all(isinstance(value, str) and value for value in account.values()):
            raise RuntimeError("TradeSea did not provide a stable account identity.")
        if self.reference and self.reference != account:
            raise RuntimeError("The Asia account changed. Refusing to switch or discard its saved deadline.")
        remote, now = api.get()
        self.check_time(now)
        if remote and remote["start"] > now:
            raise RuntimeError("TradeSea has a future scheduled lockout. It has not been replaced.")
        if self.state is None or self.state["cycle"]["finished"]:
            # Import an existing full-length active lock without extending its
            # original deadline. A new cycle always has a full twelve hours.
            if remote and remote["end"] > now:
                start, end = remote["start"], remote["end"]
                source = "existing"
            else:
                start, end = now, now + self.duration_seconds
                source = "scheduled"
            self.state = {"version": 1, "account": account, "serverFloor": now,
                          "durationSeconds": self.duration_seconds,
                          "cycle": {"start": start, "end": end, "source": source, "confirmed": False, "finished": False}}
        cycle = self.state["cycle"]
        self.state["serverFloor"] = now
        if remote and remote["end"] > now:
            cycle["end"] = max(cycle["end"], remote["end"])
        if now >= cycle["end"]:
            if not cycle["confirmed"]:
                self.save()
                raise MissedDeadline("The saved Asia lockout reached its deadline without confirmation. It has not been reset.")
            cycle["finished"] = True
            self.save()
            return "finished"
        cycle["confirmed"] = bool(remote and remote["start"] <= now and remote["end"] >= cycle["end"])
        self.save()
        if cycle["confirmed"]:
            return "confirmed"
        confirmed, server_now = api.put(cycle.copy())
        self.check_time(server_now)
        self.state["serverFloor"] = server_now
        if confirmed and confirmed["start"] <= server_now and confirmed["end"] > server_now:
            cycle["end"] = max(cycle["end"], confirmed["end"])
            cycle["confirmed"] = confirmed["end"] >= cycle["end"]
        self.save()
        if not cycle["confirmed"]:
            raise RuntimeError("TradeSea has not confirmed the complete Asia lockout. This run failed; the saved deadline is retained.")
        return "confirmed"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Apply the fixed twelve-hour Asia lockout, confirm it once, and exit.")
    parser.add_argument("--headless", action="store_true", help="reuse the saved login without showing Chrome")
    parser.add_argument("--login-only", action="store_true", help="refresh the saved login without requesting a lockout")
    parser.add_argument("--self-check", action="store_true", help="check this installation offline without logging in or applying a lockout")
    return parser.parse_args(argv)


def run_once(protection, *, headless=False, authenticate=get_tradesea_session, api_factory=LockoutApi):
    try:
        session = authenticate(headless=headless, reference=protection.reference)
        api = api_factory(session)
        status = protection.step(session, api)
        if status == "finished":
            # A later scheduled invocation can start a new cycle after verifying
            # the previous cycle's expiry. There is no polling or retry loop.
            status = protection.step(session, api)
        if status != "confirmed":
            raise RuntimeError("TradeSea has not confirmed the Asia lockout.")
        end = datetime.fromtimestamp(protection.state["cycle"]["end"], timezone.utc).astimezone().isoformat(timespec="seconds")
        logging.info("Asia lockout confirmed until %s. Request complete; the program is exiting.", end)
        return 0
    except Exception as exc:
        logging.error("Asia lockout failed: %s", exc)
        return 1


def self_check():
    # Exercises the same production request path with an in-memory server.
    # This option cannot contact TradeSea or create a real saved lockout.
    from copy import deepcopy
    from email.utils import format_datetime
    from playwright.sync_api import sync_playwright
    from playwright._impl._driver import compute_driver_executable
    import certifi

    class Memory:
        def __init__(self):
            self.value = None
        def load(self):
            return deepcopy(self.value)
        def save(self, value):
            self.value = deepcopy(validate_state(value))

    class Response:
        status_code = 200
        def __init__(self, body):
            self.body = body
            self.headers = {"Date": format_datetime(datetime(2026, 9, 10, tzinfo=timezone.utc), usegmt=True)}
        def json(self):
            return self.body

    class Server:
        def __init__(self, store):
            self.store, self.calls, self.lock = store, [], None
        def request(self, method, url, **kwargs):
            self.calls.append(method)
            if method == "PUT":
                payload = kwargs["json"]
                assert payload["lockoutEndTimeEpoch"] == self.store.value["cycle"]["end"]
                self.lock = dict(payload)
                return Response({"status": "success"})
            assert method == "GET"
            return Response({"status": "success", "data": self.lock or {}})

    memory = Memory()
    server = Server(memory)
    session = TradeSeaSession("OFFLINE-TEST", "", "offline-account", "OFFLINE-ACCOUNT", "LF")
    result = run_once(AsiaProtection(memory), authenticate=lambda **kwargs: session,
                      api_factory=lambda _session: LockoutApi(session, server))
    assert result == 0 and server.calls == ["GET", "PUT", "GET"]
    assert memory.value["cycle"]["end"] - memory.value["cycle"]["start"] == 43200
    end = memory.value["cycle"]["end"]
    result = run_once(AsiaProtection(memory), authenticate=lambda **kwargs: session,
                      api_factory=lambda _session: LockoutApi(session, server))
    assert result == 0 and server.calls == ["GET", "PUT", "GET", "GET"]
    assert memory.value["cycle"]["end"] == end
    driver, cli = compute_driver_executable()
    assert Path(driver).is_file() and Path(cli).is_file() and Path(certifi.where()).is_file()
    try:
        obfuscated = callable(__pyarmor__)
    except NameError:
        obfuscated = False
    report = {"ok": True, "obfuscated": obfuscated, "durationHours": 12, "periodicChecks": False,
              "requestSequence": server.calls, "browserDriverIncluded": True, "applicationDirectory": str(ROOT),
              "loginProfileDirectory": str(ROOT / ".tradesea-browser-profile")}
    (ROOT / "self-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


def main(argv=None):
    args = parse_args(argv)
    if args.self_check:
        return self_check()
    handlers = [RotatingFileHandler(ROOT / "asia-lockout.log", maxBytes=200_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    try:
        if args.login_only:
            saved = StateStore().load()
            get_tradesea_session(headless=args.headless, reference=saved["account"] if saved else None)
            logging.info("TradeSea login is ready. No lockout request was sent.")
            return 0
        with single_instance():
            return run_once(AsiaProtection(StateStore()), headless=args.headless)
    except Exception as exc:
        logging.error("Protection could not start: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
