"""Qt Quick UI. Native transparent window; service operations remain unchanged."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import logging

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QTimer
from PySide6.QtGui import QGuiApplication, QFont, QPalette, QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuick import QQuickWindow
from panel_bridge import PanelBridge
from tradesea_lockout import DURATIONS, ROOT


class PanelController(QObject):
    changed = Signal()
    completed = Signal(object, str, bool)

    def __init__(self, service, preview=False):
        super().__init__()
        self._bridge = PanelBridge(service)
        self._preview = preview
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._accounts = []
        self._duration = 43200
        self._busy = self._loaded = self._dirty = False
        self._message = 'Connecting saved login…'
        self._connection = 'Connecting…'
        self._schedule = 'Sun–Thu · 5:00 PM local'
        self._error = False
        self.completed.connect(self._complete)

    @Property('QVariantMap', notify=changed)
    def state(self):
        return dict(accounts=self._accounts, duration=self._duration, busy=self._busy,
                    loaded=self._loaded, dirty=self._dirty, message=self._message,
                    connection=self._connection, schedule=self._schedule,
                    error=self._error, preview=self._preview,
                    allocated=sum(a['category'] is not None for a in self._accounts))

    def _note(self, text, error=False):
        self._message, self._error = text, error
        self.changed.emit()

    def _apply(self, data):
        self._duration = data['duration']
        self._accounts = deepcopy(data['accounts'])
        for account in self._accounts:
            account['savedDuration'] = 86400 if account['category'] == 'day' else self._duration
            status = account['status']
            account['restricted'] = not status.get('verified') or status.get('locked', True)
            if not status.get('verified'):
                account['statusText'] = 'Status unavailable'
            elif status.get('locked'):
                account['statusText'] = ('Locked until ' + datetime.fromtimestamp(status['end']).strftime('%b %d, %I:%M %p')) if status.get('end') else 'Locked · deadline unavailable'
            else:
                account['statusText'] = 'Ready for next scheduled run'
        self._schedule = data['schedule']
        self._loaded, self._dirty = not data.get('missing'), False
        self._connection = 'Preview mode' if self._preview else 'Saved login connected'
        self._note('A saved account is unavailable. Refresh before saving.' if data.get('missing') else 'Drag accounts between categories, or expand Unallocated to add one.', bool(data.get('missing')))

    def _submit(self, function, saving=False):
        if self._busy:
            return
        self._busy = True
        self.changed.emit()
        future = self._pool.submit(function)
        def done(f):
            try:
                result = f.result()
                self.completed.emit(result, '', saving)
            except Exception as exc:
                logging.warning('Panel operation failed: %s', exc)
                self.completed.emit(None, str(exc), saving)
        future.add_done_callback(done)

    @Slot(object, str, bool)
    def _complete(self, result, error, saving):
        self._busy = False
        if error:
            if not saving:
                self._loaded = False
                self._connection = 'Connection needs attention'
            self._note(error, True)
        else:
            self._apply(result)
            if saving:
                self._note('Saved. Automatic lockouts scheduled Sunday-Thursday at 5:00 PM local.')

    @Slot()
    def start(self):
        if self._preview:
            names = [('LUCID • PRO 011', 'asia'), ('LUCID • PRO 024', 'asia'),
                     ('LUCID • PRO 038', 'day'), ('LUCID • PRO 042', None), ('LUCID • PRO 056', None)]
            self._apply(dict(duration=43200, schedule='Sun–Thu · 5:00 PM local', accounts=[
                dict(key=str(i), name=name, category=category,
                     reference=dict(externalAccountId='DEMO-'+str(i), accountType='RS', propFirm='LucidTrading'),
                     status=dict(verified=True, locked=False)) for i,(name,category) in enumerate(names)]))
        else:
            self.refresh(False)

    @Slot(bool)
    def refresh(self, interactive=False):
        if self._preview:
            self._note('This preview uses sample accounts. Open the app normally for live accounts.')
            return
        if self._busy:
            return
        self._note('Complete sign in in Chrome.' if interactive else 'Refreshing saved login and account status…')
        self._submit(lambda: self._bridge.load(interactive))

    @Slot(str, str)
    def moveAccount(self, key, category):
        if self._busy or not self._loaded:
            return
        if category not in ('asia', 'day', 'none'):
            return
        account = next((a for a in self._accounts if a['key'] == key), None)
        category = None if category == 'none' else category
        if not account or account['category'] == category:
            return
        duration = 86400 if category == 'day' else self._duration
        if category and account['restricted'] and duration != account['savedDuration']:
            self._note('This account’s duration is fixed until its lockout ends and its status is verified.', True)
            return
        account['category'] = category
        self._dirty = True
        self._note('Unsaved changes · Save to update the next scheduled run.')

    @Slot(int)
    def setDuration(self, duration):
        if self._busy or not self._loaded or duration not in DURATIONS:
            return
        if any(a['category'] == 'asia' and a['restricted'] and a['savedDuration'] != duration for a in self._accounts):
            self._note('Asia duration is fixed while an allocated account is locked or unverified.', True)
            return
        self._duration = duration
        self._dirty = True
        self._note('Unsaved changes · Save to update the next scheduled run.')

    @Slot()
    def save(self):
        if self._busy or not self._loaded:
            return
        if self._preview:
            for a in self._accounts:
                a['savedDuration'] = 86400 if a['category'] == 'day' else self._duration
            self._dirty = False
            self._note('Preview allocation saved for this session.')
            return
        settings = dict(version=2, mode='selected', durationSeconds=self._duration,
                        accounts=[dict(a['reference'], category=a['category']) for a in self._accounts if a['category']])
        self._note('Verifying lockouts and saving…')
        self._submit(lambda: self._bridge.save(settings), saving=True)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


def show_panel(service, preview=False, check=False):
    QQuickStyle.setStyle('Basic')
    app = QGuiApplication.instance() or QGuiApplication([])
    app.setApplicationName('TradeSea')
    app.setOrganizationName('TradeSea')
    app.setFont(QFont('Segoe UI', 10))
    palette = QPalette()
    for role, color in ((QPalette.Window, '#28263b'), (QPalette.WindowText, '#f0ecff'),
                        (QPalette.Base, '#232136'), (QPalette.Text, '#f0ecff'),
                        (QPalette.Button, '#36314a'), (QPalette.ButtonText, '#f0ecff'),
                        (QPalette.Highlight, '#a695d9'), (QPalette.HighlightedText, '#211b32')):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    controller = PanelController(service, preview)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('panelController', controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('panel.qml'))))
    if not engine.rootObjects():
        controller.shutdown()
        return 1
    if check:
        def verify_surface():
            window = engine.rootObjects()[0]
            image = window.grabWindow()
            corners = [(0, 0), (4, 4), (image.width()-1, 0),
                       (0, image.height()-1), (image.width()-1, image.height()-1)]
            alpha = [image.pixelColor(x, y).alpha() for x, y in corners] if not image.isNull() else []
            ok = bool(alpha) and all(value == 0 for value in alpha) and image.pixelColor(50, 50).alpha() >= 250
            (ROOT / '.asia-ui-check.json').write_text(json.dumps(dict(ok=ok, renderer='Qt Quick',
                cornerAlpha=alpha, width=image.width(), height=image.height()), indent=2))
            app.exit(0 if ok else 1)
        QTimer.singleShot(1500, verify_surface)
    result = app.exec()
    controller.shutdown()
    return result
