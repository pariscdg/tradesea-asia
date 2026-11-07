import contextlib
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from tradesea_auth import TradeSeaSession, get_lucid_account, get_lucid_account_id
from tradesea_lockout import (AsiaProtection, StateStore, LockoutApi, LoginRequired, MissedDeadline,
                              main, parse_args, read_server_lock, run_once, single_instance, validate_state)


SESSION = TradeSeaSession("fake-test-token", "", "account-123", "TEST-EXTERNAL", "LF")
HOURS_12 = 43200


class MemoryStore:
    def __init__(self, state=None):
        self.saved = deepcopy(state)
        self.fail = False

    def load(self):
        return deepcopy(self.saved)

    def save(self, state):
        if self.fail:
            raise OSError("Simulated storage failure")
        self.saved = deepcopy(validate_state(state))


class FakeApi:
    def __init__(self, store):
        self.now = 1788980000
        self.remote = None
        self.store = store
        self.puts = []
        self.confirm = True

    def get(self):
        return deepcopy(self.remote), self.now

    def put(self, cycle):
        # Enforce the durability contract in every test that submits a lock.
        assert self.store.load()["cycle"]["end"] == cycle["end"]
        self.puts.append(deepcopy(cycle))
        if self.confirm:
            self.remote = {"start": cycle["start"], "end": cycle["end"]}
        return self.get()


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.api = FakeApi(self.store)
        self.protection = AsiaProtection(self.store)

    def start(self):
        self.assertEqual(self.protection.step(SESSION, self.api), "confirmed")
        return self.store.saved["cycle"]["end"]

    def test_new_lock_is_twelve_hours_and_saved_before_put(self):
        end = self.start()
        self.assertEqual(end, self.api.now + HOURS_12)
        self.assertTrue(self.store.saved["cycle"]["confirmed"])

    def test_old_duration_constant_cannot_shorten_new_lock(self):
        with patch("tradesea_lockout.DEFAULT_LOCKOUT_SECONDS", 5, create=True):
            self.assertEqual(self.start() - self.api.now, HOURS_12)

    def test_removed_duration_flag_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parse_args(["--seconds", "5"])
        self.assertEqual(raised.exception.code, 2)

    def test_rerun_retains_absolute_deadline(self):
        end = self.start()
        self.api.now += 3600
        restarted = AsiaProtection(self.store)
        restarted.step(SESSION, self.api)
        self.assertEqual(self.store.saved["cycle"]["end"], end)
        self.assertEqual(len(self.api.puts), 1)

    def test_shortened_server_lock_is_restored_after_restart(self):
        end = self.start()
        self.api.now += 100
        self.api.remote = {"start": self.api.now, "end": self.api.now + 5}
        AsiaProtection(self.store).step(SESSION, self.api)
        self.assertEqual(self.api.puts[-1]["end"], end)
        self.assertEqual(self.store.saved["cycle"]["end"], end)

    def test_longer_server_lock_is_preserved(self):
        self.start()
        self.api.remote["end"] += 8000
        end = self.api.remote["end"]
        self.protection.step(SESSION, self.api)
        self.assertEqual(self.store.saved["cycle"]["end"], end)
        self.assertEqual(len(self.api.puts), 1)

    def test_import_existing_twelve_hour_lock_keeps_end(self):
        self.api.remote = {"start": self.api.now - 5000, "end": self.api.now - 5000 + HOURS_12}
        end = self.api.remote["end"]
        self.assertEqual(self.start(), end)
        self.assertEqual(self.api.puts, [])

    def test_existing_eight_hour_lock_never_shortened(self):
        self.api.remote = {"start": self.api.now, "end": self.api.now + 28800}
        self.assertEqual(self.start(), self.api.now + 28800)
        self.assertEqual(self.api.puts, [])

    def test_future_scheduled_lock_not_overwritten(self):
        self.api.remote = {"start": self.api.now + 60, "end": self.api.now + HOURS_12}
        with self.assertRaisesRegex(RuntimeError, "future scheduled"):
            self.start()
        self.assertEqual(self.api.puts, [])
        self.assertIsNone(self.store.saved)

    def test_unconfirmed_put_never_reported_success_or_new_deadline(self):
        self.api.confirm = False
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            self.start()
        end = self.store.saved["cycle"]["end"]
        self.assertFalse(self.store.saved["cycle"]["confirmed"])
        self.api.now += 200
        self.api.confirm = True
        self.assertEqual(AsiaProtection(self.store).step(SESSION, self.api), "confirmed")
        self.assertEqual(self.api.puts[-1]["end"], end)

    def test_missed_unconfirmed_deadline_does_not_reset(self):
        self.api.confirm = False
        with self.assertRaises(RuntimeError):
            self.start()
        end = self.store.saved["cycle"]["end"]
        self.api.now = end + 1
        with self.assertRaises(MissedDeadline):
            AsiaProtection(self.store).step(SESSION, self.api)
        self.assertEqual(self.store.saved["cycle"]["end"], end)
        self.assertEqual(len(self.api.puts), 1)

    def test_storage_failure_sends_no_put(self):
        self.store.fail = True
        with self.assertRaises(OSError):
            self.start()
        self.assertEqual(self.api.puts, [])

    def test_local_clock_changes_do_not_expire_lock(self):
        end = self.start()
        with patch("time.time", return_value=end + 1000000):
            self.protection.step(SESSION, self.api)
        self.assertFalse(self.store.saved["cycle"]["finished"])

    def test_server_time_cannot_move_backward(self):
        self.start()
        self.api.now -= 1
        with self.assertRaisesRegex(RuntimeError, "backwards"):
            self.protection.step(SESSION, self.api)
        self.assertEqual(len(self.api.puts), 1)

    def test_verified_expiry_finishes_without_unlock_request(self):
        self.api.now = self.start()
        self.assertEqual(self.protection.step(SESSION, self.api), "finished")
        self.assertTrue(self.store.saved["cycle"]["finished"])
        self.assertEqual(len(self.api.puts), 1)

    def test_another_account_cannot_replace_saved_target(self):
        self.start()
        different = TradeSeaSession("fake", "", "another", "DIFFERENT", "LF")
        with self.assertRaisesRegex(RuntimeError, "account changed"):
            self.protection.step(different, self.api)
        self.assertEqual(len(self.api.puts), 1)

    def test_refresh_request_id_preserves_identity_and_end(self):
        end = self.start()
        refreshed = TradeSeaSession("new-test-token", "", "refreshed-id", SESSION.external_account_id, SESSION.account_type)
        AsiaProtection(self.store).step(refreshed, self.api)
        self.assertEqual(self.store.saved["cycle"]["end"], end)

    def test_tampered_short_record_is_rejected(self):
        self.start()
        changed = deepcopy(self.store.saved)
        changed["cycle"]["end"] = changed["cycle"]["start"] + 5
        with self.assertRaisesRegex(ValueError, "shorter than twelve"):
            validate_state(changed)

    def test_expired_login_fails_once_without_background_retry(self):
        end = self.start()
        expired = Mock()
        expired.get.side_effect = LoginRequired("expired test login")
        auth = Mock(return_value=SESSION)
        with self.assertLogs(level="INFO"):
            result = run_once(AsiaProtection(self.store), authenticate=auth,
                              api_factory=lambda session: expired)
        self.assertEqual(result, 1)
        self.assertEqual(auth.call_count, 1)
        expired.get.assert_called_once_with()
        expired.put.assert_not_called()
        self.assertEqual(self.store.saved["cycle"]["end"], end)

    def test_next_scheduled_run_recovers_expired_interrupted_cycle(self):
        end = self.start()
        self.api.now = end + 1000
        new_start = self.api.now
        with self.assertLogs(level="INFO"):
            result = run_once(AsiaProtection(self.store), authenticate=lambda **kw: SESSION,
                              api_factory=lambda session: self.api)
        self.assertEqual(result, 0)
        self.assertEqual(self.api.puts[-1]["end"], new_start + HOURS_12)
        self.assertEqual(len(self.api.puts), 2)

    def test_success_returns_after_one_submission_and_confirmation(self):
        auth = Mock(return_value=SESSION)
        with patch.object(self.api, "get", wraps=self.api.get) as get, self.assertLogs(level="INFO"):
            result = run_once(self.protection, authenticate=auth, api_factory=lambda session: self.api)
        self.assertEqual(result, 0)
        self.assertEqual(len(self.api.puts), 1)
        self.assertEqual(get.call_count, 2)
        auth.assert_called_once_with(headless=False, reference=None)

    def test_failed_confirmation_returns_once_and_retains_deadline(self):
        self.api.confirm = False
        with self.assertLogs(level="ERROR"):
            result = run_once(self.protection, authenticate=lambda **kw: SESSION, api_factory=lambda session: self.api)
        self.assertEqual(result, 1)
        self.assertEqual(len(self.api.puts), 1)
        self.assertFalse(self.store.saved["cycle"]["confirmed"])


class DiskStateTests(unittest.TestCase):
    def test_atomic_round_trip_and_failed_replace_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(Path(folder) / "saved.json")
            api = FakeApi(store)
            guard = AsiaProtection(store)
            guard.step(SESSION, api)
            original = store.load()
            changed = deepcopy(original)
            changed["cycle"]["end"] += 60
            with patch("tradesea_lockout.os.replace", side_effect=OSError("simulated failure")), self.assertRaises(OSError):
                store.save(changed)
            self.assertEqual(store.load(), original)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_corrupt_file_is_not_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "saved.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "cannot be read"):
                StateStore(path).load()
            self.assertEqual(path.read_text(), "broken")

    def test_second_local_process_guard_cannot_enter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mutex"
            with single_instance(path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with single_instance(path):
                        self.fail("Second guardian entered")
            with single_instance(path):
                pass


class ApiTests(unittest.TestCase):
    def response(self, body, status=200, date=1788980000):
        response = Mock(status_code=status)
        response.headers = {"Date": format_datetime(datetime.fromtimestamp(date, timezone.utc), usegmt=True)}
        response.json.return_value = body
        return response

    def test_acknowledgement_followed_by_get_and_cookies_not_redirected(self):
        transport = Mock()
        transport.request.side_effect = [self.response({"status": "success"}, 201), self.response({"status": "success", "data": {
            "lockoutStartTimeEpoch": 1788980000, "lockoutEndTimeEpoch": 1788980000 + HOURS_12}})]
        remote, now = LockoutApi(SESSION, transport).put({"start": 1788980000, "end": 1788980000 + HOURS_12})
        self.assertEqual(remote["end"] - now, HOURS_12)
        self.assertEqual([call.args[0] for call in transport.request.call_args_list], ["PUT", "GET"])
        self.assertFalse(transport.request.call_args.kwargs["allow_redirects"])
        self.assertEqual(transport.request.call_args.kwargs["headers"]["Cookie"], "access_token=fake-test-token")

    def test_short_payload_blocked_before_http(self):
        transport = Mock()
        with self.assertRaises(ValueError):
            LockoutApi(SESSION, transport).put({"start": 1000, "end": 1005})
        transport.request.assert_not_called()

    def test_missing_server_time_or_malformed_lock_is_not_confirmation(self):
        transport = Mock()
        response = self.response({"status": "success", "data": {}})
        response.headers = {}
        transport.request.return_value = response
        with self.assertRaisesRegex(RuntimeError, "server time"):
            LockoutApi(SESSION, transport).get()
        for body in ({}, {"status": "error", "data": {}}, {"status": "ok", "data": {"lockoutEndTimeEpoch": 99}},
                     {"status": "ok", "data": {"lockoutStartTimeEpoch": False, "lockoutEndTimeEpoch": False}}):
            with self.assertRaises(RuntimeError):
                read_server_lock(body)

    def test_error_does_not_print_server_body_or_token(self):
        transport = Mock()
        response = self.response({"private": "not for logs"}, 500)
        transport.request.return_value = response
        with self.assertRaisesRegex(RuntimeError, "HTTP 500") as error:
            LockoutApi(SESSION, transport).get()
        self.assertNotIn("private", str(error.exception))
        self.assertNotIn(SESSION.access_token, str(error.exception))

    def test_network_failure_is_safe_error(self):
        transport = Mock()
        transport.request.side_effect = requests.ConnectionError("test")
        with self.assertRaisesRegex(RuntimeError, "could not be reached"):
            LockoutApi(SESSION, transport).get()


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.account = {"id": "lucid-account", "propFirm": "LucidTrading", "type": "live",
                        "externalAccountId": "TEST-EXTERNAL", "accountType": "LF"}

    @patch("tradesea_auth.requests.get")
    def test_selects_lucid_account_not_demo(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"s": "success", "d": [self.account, {**self.account, "propFirm": "sandbox"}]}
        self.assertEqual(get_lucid_account_id("fake"), "lucid-account")

    @patch("tradesea_auth.requests.get")
    def test_refresh_can_find_locked_pinned_account_among_several(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"s": "success", "d": [
            {**self.account, "type": "locked", "id": "refreshed"},
            {**self.account, "externalAccountId": "OTHER", "id": "other"}]}
        reference = {"externalAccountId": "TEST-EXTERNAL", "accountType": "LF"}
        self.assertEqual(get_lucid_account("fake", reference)["id"], "refreshed")
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            get_lucid_account("fake")

    @patch("tradesea_auth.requests.get")
    def test_missing_pinned_account_is_not_silently_replaced(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"s": "success", "d": [self.account]}
        with self.assertRaisesRegex(RuntimeError, "not been switched"):
            get_lucid_account("fake", {"externalAccountId": "MISSING", "accountType": "LF"})

    def test_login_only_never_starts_lockout_guardian(self):
        with patch("tradesea_lockout.RotatingFileHandler", return_value=logging.NullHandler()), \
             patch("tradesea_lockout.logging.basicConfig"), \
             patch("tradesea_lockout.StateStore") as store, \
             patch("tradesea_lockout.get_tradesea_session") as login, \
             patch("tradesea_lockout.run_once") as run:
            store.return_value.load.return_value = None
            self.assertEqual(main(["--login-only"]), 0)
            login.assert_called_once_with(headless=False, reference=None)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
