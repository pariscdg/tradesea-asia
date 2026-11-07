"""Shared data adapter for the native panel; no GUI runtime dependency."""
from threading import Lock
from panel_schedule import schedule_status, ensure_schedule
from asia_settings import account_key, identity, label, resolve_accounts

class PanelBridge:
    def __init__(self, service):
        self.service = service
        self.guard = Lock()

    def present(self, result):
        settings = result['settings']
        selected, missing = resolve_accounts(settings, result['accounts'])
        keys = {account_key(a) for a in selected}
        refs = {account_key(a): a for a in settings['accounts']}
        accounts = []
        for a in result['accounts']:
            key = account_key(a)
            category = None
            if key in keys:
                category = refs[key]['category'] if settings['version'] == 2 else ('day' if settings['durationSeconds'] == 86400 else 'asia')
            accounts.append(dict(key=key, name=label(a), reference=identity(a), category=category,
                                 status=result['statuses'].get(key, {})))
        return dict(accounts=accounts, duration=settings['durationSeconds'], schedule=schedule_status(),
                    missing=len(missing), lastRun=result.get('lastRun'))

    def load(self, interactive=False):
        with self.guard:
            return self.present(self.service.load(interactive))

    def save(self, settings):
        with self.guard:
            result = self.service.save(settings)
            try:
                ensure_schedule()
            except Exception as exc:
                raise RuntimeError('Settings saved, but scheduling failed. Click Save changes to retry. ' + str(exc)) from exc
            return self.present(result)
