from copy import deepcopy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from asia_panel import AsiaPanel
from asia_service import AsiaService
from asia_settings import Repository, account_key, defaults, identity, resolve_accounts, validate_settings
from tradesea_lockout import AsiaProtection
from tradesea_auth import TradeSeaSession


EPOCH = 1800000000


def account(number, lucid=True):
    return {"id": f"request-{number}", "externalAccountId": f"TEST-{number}", "accountType": "LF" if lucid else "RD",
            "propFirm": "LucidTrading" if lucid else "Demo", "name": f"{'Lucid' if lucid else 'Demo'} account {number}", "type": "live"}


class Harness:
    def __init__(self, root):
        self.repo = Repository(root)
        self.accounts = [account(1), account(2), account(3, False)]
        self.now, self.remotes, self.puts, self.gets, self.failed = EPOCH, {}, [], [], set()
        self.auth = Mock(return_value="fake-cookie")
        self.service = AsiaService(self.repo, self.auth, lambda _: deepcopy(self.accounts), self.api)

    def api(self, session):
        harness = self
        external = session.external_account_id
        matched = next(a for a in self.accounts if a["id"] == session.account_id)
        class Api:
            def get(self):
                harness.gets.append(session.account_id)
                if external in harness.failed:
                    raise RuntimeError("Offline")
                return deepcopy(harness.remotes.get(external)), harness.now
            def put(self, cycle):
                saved = harness.repo.store(matched).load()
                assert saved["cycle"]["end"] == cycle["end"]
                harness.puts.append((external, deepcopy(cycle)))
                harness.remotes[external] = {"start": cycle["start"], "end": cycle["end"]}
                return self.get()
        return Api()

    def selected(self, indexes, duration=43200):
        return {"version": 1, "mode": "selected", "durationSeconds": duration,
                "accounts": [identity(self.accounts[i]) for i in indexes]}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = Harness(self.temp.name)

    def test_panel_load_defaults_all_lucid_and_never_locks(self):
        result = self.h.service.load()
        chosen, missing = resolve_accounts(result["settings"], result["accounts"])
        self.assertEqual([a["id"] for a in chosen], ["request-1", "request-2"])
        self.assertEqual(result["settings"]["durationSeconds"], 43200)
        self.assertFalse(missing)
        self.assertEqual(self.h.puts, [])
        self.h.auth.assert_called_once_with(headless=True, timeout_seconds=45)

    def test_saving_settings_never_locks_or_stores_auth_cookie(self):
        self.h.service.save(self.h.selected([0, 2], 7200))
        text = self.h.repo.settings_path.read_text()
        self.assertNotIn("fake-cookie", text)
        self.assertNotIn("request-1", text)
        self.assertEqual(self.h.repo.settings()["durationSeconds"], 7200)
        self.assertEqual(self.h.puts, [])

    def test_default_runner_locks_every_lucid_once_and_exits(self):
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual([a for a, _ in self.h.puts], ["TEST-1", "TEST-2"])
        self.assertTrue(all(c["end"] - c["start"] == 43200 for _, c in self.h.puts))
        self.assertEqual(len(self.h.gets), 4)
        self.assertTrue(self.h.repo.last_run()["ok"])
        self.assertEqual(self.h.auth.call_count, 1)

    def test_selected_accounts_and_duration_used_on_next_run(self):
        self.h.service.save(self.h.selected([1, 2], 3600))
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual([a for a, _ in self.h.puts], ["TEST-2", "TEST-3"])
        self.assertTrue(all(c["end"] - c["start"] == 3600 for _, c in self.h.puts))

    def test_active_lock_disables_duration_and_backend_rejects_change(self):
        self.h.service.run()
        saved = self.h.repo.store(self.h.accounts[0]).load()
        with self.assertRaisesRegex(RuntimeError, "Duration cannot change"):
            self.h.service.save(self.h.selected([0], 3600))
        self.assertEqual(self.h.repo.store(self.h.accounts[0]).load(), saved)
        self.assertEqual(self.h.repo.settings()["durationSeconds"], 43200)

    def test_existing_server_lock_is_unchanged_even_if_duration_setting_differs(self):
        self.h.remotes["TEST-1"] = {"start": EPOCH - 100, "end": EPOCH + 3500}
        self.h.service.run()
        self.assertEqual([a for a, _ in self.h.puts], ["TEST-2"])
        self.assertEqual(self.h.repo.store(self.h.accounts[0]).load()["cycle"]["end"], EPOCH + 3500)

    def test_edited_duration_file_cannot_shorten_active_deadlines(self):
        self.h.service.run()
        self.h.repo.save_settings({**defaults(), "durationSeconds": 3600})
        self.h.now += 60
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual(len(self.h.puts), 2)
        for a in self.h.accounts[:2]:
            self.assertEqual(self.h.repo.store(a).load()["cycle"]["end"], EPOCH + 43200)

    def test_selected_account_refreshes_opaque_id_without_switching_identity(self):
        self.h.service.save(self.h.selected([1], 7200))
        self.h.accounts[1]["id"] = "fresh-request-id"
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual([a for a, _ in self.h.puts], ["TEST-2"])

    def test_missing_selection_and_failed_account_do_not_stop_other_selected_locks(self):
        self.h.repo.save_settings(self.h.selected([0, 1, 2]))
        self.h.accounts.pop(2)
        self.h.failed.add("TEST-1")
        self.assertEqual(self.h.service.run(), 1)
        self.assertEqual([a for a, _ in self.h.puts], ["TEST-2"])
        self.assertEqual(len(self.h.repo.last_run()["results"]), 3)

    def test_unknown_lock_status_cannot_enable_duration_change(self):
        self.h.failed.add("TEST-1")
        result = self.h.service.load()
        self.assertFalse(result["statuses"][account_key(self.h.accounts[0])]["verified"])
        with self.assertRaisesRegex(RuntimeError, "Duration cannot change"):
            self.h.service.save(self.h.selected([0], 3600))
        self.assertEqual(self.h.puts, [])

    def test_expired_lock_allows_duration_change_for_next_run(self):
        self.h.service.run()
        self.h.now += 43201
        self.h.service.save(self.h.selected([0], 7200))
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual(self.h.puts[-1][1]["end"], self.h.now + 7200)

    def test_unselected_locked_account_keeps_its_deadline_when_new_account_selected(self):
        self.h.service.run()
        end = self.h.repo.store(self.h.accounts[0]).load()["cycle"]["end"]
        self.h.service.save(self.h.selected([2], 3600))
        self.h.service.run()
        self.assertEqual(self.h.repo.store(self.h.accounts[0]).load()["cycle"]["end"], end)
        self.assertEqual(self.h.puts[-1][0], "TEST-3")

    def test_legacy_deadline_migrates_without_mutating_original_file(self):
        target = self.h.repo.root / ".asia-lockout.json"
        from tradesea_lockout import StateStore
        store = StateStore(target)
        state = {"version": 1, "account": {"externalAccountId": "TEST-1", "accountType": "LF"},
                 "serverFloor": EPOCH, "cycle": {"start": EPOCH, "end": EPOCH + 43200, "confirmed": True, "finished": False}}
        store.save(state)
        original = target.read_bytes()
        self.h.service.load()
        self.assertEqual(self.h.repo.store(self.h.accounts[0]).load(), state)
        self.assertEqual(target.read_bytes(), original)

    def test_ambiguous_or_empty_selection_and_invalid_duration_rejected(self):
        for settings in [self.h.selected([], 43200), self.h.selected([0], 5), self.h.selected([0, 0], 3600)]:
            with self.assertRaises(ValueError):
                validate_settings(settings)
        self.h.accounts.append(deepcopy(self.h.accounts[0]))
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.h.service.load()

    def test_save_rechecks_a_lock_that_started_after_panel_load(self):
        self.h.service.load()
        self.h.remotes["TEST-1"] = {"start": EPOCH, "end": EPOCH + 43200}
        with self.assertRaisesRegex(RuntimeError, "Duration cannot change"):
            self.h.service.save(self.h.selected([0], 3600))
        self.assertEqual(self.h.puts, [])


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = Harness(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.panel = AsiaPanel(self.root, self.h.service, read_schedule=lambda: "Next scheduled run", auto_load=False)

    def test_default_all_lucid_and_live_lock_greys_duration(self):
        self.panel.loaded_result(self.h.service.load())
        self.panel.render()
        self.assertEqual(len(self.panel.selected), 2)
        self.assertEqual(str(self.panel.duration_box["state"]), "readonly")
        self.h.service.run()
        self.panel.loaded_result(self.h.service.load())
        self.panel.render()
        self.assertEqual(str(self.panel.duration_box["state"]), "disabled")
        self.assertIn("locked", self.panel.lock_note["text"])

    def test_choosing_an_unlocked_account_enables_duration_without_touching_existing_lock(self):
        self.h.service.run()
        self.panel.loaded_result(self.h.service.load())
        self.panel.toggle(account_key(self.h.accounts[0]))
        self.panel.toggle(account_key(self.h.accounts[1]))
        self.panel.toggle(account_key(self.h.accounts[2]))
        self.assertEqual(str(self.panel.duration_box["state"]), "readonly")
        self.assertEqual(self.panel.mode, "selected")
        self.assertEqual(len(self.h.puts), 2)

    def test_loading_or_unknown_status_keeps_duration_disabled(self):
        self.assertEqual(str(self.panel.duration_box["state"]), "disabled")
        self.h.failed.add("TEST-1")
        self.panel.loaded_result(self.h.service.load())
        self.panel.render()
        self.assertEqual(str(self.panel.duration_box["state"]), "disabled")


if __name__ == "__main__":
    unittest.main()
