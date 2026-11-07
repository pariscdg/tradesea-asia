"""Installation check with simulated accounts; never contacts TradeSea."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from panel_bridge import PanelBridge
from asia_service import AsiaService
from asia_settings import Repository, account_key, identity
from tradesea_lockout import ROOT, DURATIONS, self_check


def installation_check():
    self_check()
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(directory)
        accounts = [{"id": f"test-{i}", "externalAccountId": f"OFFLINE-{i}", "accountType": "LF",
                     "propFirm": "LucidTrading" if i < 3 else "Demo", "type": "live", "name": f"Test account {i}"}
                    for i in (1, 2, 3)]
        remotes, puts, calls = {}, [], []
        def api_factory(session):
            account = next(a for a in accounts if a["id"] == session.account_id)
            class Api:
                def get(self):
                    calls.append("GET")
                    return deepcopy(remotes.get(session.account_id)), 1800000000
                def put(self, cycle):
                    assert repo.store(account).load()["cycle"]["end"] == cycle["end"]
                    calls.append("PUT")
                    puts.append(session.account_id)
                    remotes[session.account_id] = {"start": cycle["start"], "end": cycle["end"]}
                    return self.get()
            return Api()
        service = AsiaService(repo, authenticate=lambda **_: "OFFLINE-COOKIE", accounts=lambda _: accounts, api_factory=api_factory)
        assert service.run() == 0
        assert puts == ["test-1", "test-2"]
        assert calls == ["GET", "PUT", "GET", "GET", "PUT", "GET"]
        original = repo.store(accounts[0]).load()["cycle"]["end"]
        try:
            service.save({"version": 1, "mode": "selected", "durationSeconds": 3600, "accounts": [identity(accounts[0])]})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Active duration change was accepted")
        assert repo.store(accounts[0]).load()["cycle"]["end"] == original
        data = PanelBridge(service).present(service.load())
        assert len(data['accounts']) == 3
        assert data['accounts'][0]['status']['locked']
        assert data['accounts'][0]['category'] == 'asia'
        assert data['accounts'][2]['category'] is None
    path = ROOT / "self-check.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report.update({"accountPanel": True, "multiAccount": True, "lockedDurationDisabled": True,
                   "supportedDurationHours": [seconds // 3600 for seconds in DURATIONS], "defaultAllLucid": True})
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0
