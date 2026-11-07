"""Local WebView panel; only explicit Save persists allocation."""
from pathlib import Path
from threading import Lock
from asia_panel import schedule_status
from asia_settings import account_key, identity, label, resolve_accounts


class PanelBridge:
    def __init__(self, service):
        self.service = service
        self.guard = Lock()

    def present(self, result):
        settings = result['settings']
        selected, missing = resolve_accounts(settings, result['accounts'])
        selected_keys = {account_key(a) for a in selected}
        refs = {account_key(a): a for a in settings['accounts']}
        accounts = []
        for a in result['accounts']:
            key = account_key(a)
            category = None
            if key in selected_keys:
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
            return self.present(self.service.save(settings))


def show_panel(service):
    import webview
    webview.create_window('TradeSea · Automated Lockout',
                          html=Path(__file__).with_name('panel.html').read_text(encoding='utf-8'),
                          js_api=PanelBridge(service), width=930, height=760,
                          min_size=(700, 600), background_color='#10121f', text_select=False)
    webview.start(gui='edgechromium')
    return 0
