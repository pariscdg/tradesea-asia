from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
import time
from PySide6.QtCore import QCoreApplication
from qt_panel import PanelController
import test_asia_panel as legacy

class QtControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = legacy.Harness(self.temp.name)
        self.c = PanelController(self.h.service)
        self.addCleanup(self.c.shutdown)
        self.schedule = patch('panel_bridge.schedule_status',return_value='Offline schedule')
        self.schedule.start()
        self.addCleanup(self.schedule.stop)
        self.register = patch('panel_bridge.ensure_schedule')
        self.register_mock = self.register.start()
        self.addCleanup(self.register.stop)
        self.c.start()
        self.wait()

    def wait(self):
        deadline=time.monotonic()+5
        while self.c.state['busy'] and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.c.state['busy'])

    def test_save_persists_categories_without_lockout(self):
        key=self.c.state['accounts'][1]['key']
        self.c.moveAccount(key,'day')
        self.c.save()
        self.wait()
        settings=self.h.repo.settings()
        self.assertEqual(settings['version'],2)
        self.assertEqual([a['category'] for a in settings['accounts']],['asia','day'])
        self.assertEqual(self.h.puts,[])
        self.assertFalse(self.c.state['dirty'])

    def test_save_error_preserves_unsaved_assignments(self):
        key=self.c.state['accounts'][0]['key']
        self.c.moveAccount(key,'day')
        with patch.object(self.h.service,'save',side_effect=RuntimeError('Offline')):
            self.c.save()
            self.wait()
        self.assertTrue(self.c.state['dirty'])
        self.assertEqual(self.c.state['accounts'][0]['category'],'day')
        self.assertTrue(self.c.state['error'])

    def test_locked_account_cannot_change_duration(self):
        self.h.service.run()
        self.c.refresh(False)
        self.wait()
        key=self.c.state['accounts'][0]['key']
        before=deepcopy(self.h.repo.store(self.h.accounts[0]).load())
        self.c.moveAccount(key,'day')
        self.assertEqual(self.c.state['accounts'][0]['category'],'asia')
        self.c.setDuration(3600)
        self.assertEqual(self.c.state['duration'],43200)
        self.assertEqual(before,self.h.repo.store(self.h.accounts[0]).load())

    def test_unknown_status_blocks_duration_changes(self):
        self.h.failed.add('TEST-1')
        self.c.refresh(False)
        self.wait()
        self.c.moveAccount(self.c.state['accounts'][0]['key'],'day')
        self.assertEqual(self.c.state['accounts'][0]['category'],'asia')
        self.assertTrue(self.c.state['error'])

    def test_unallocate_every_account_and_save(self):
        for a in list(self.c.state['accounts']):
            self.c.moveAccount(a['key'],'none')
        self.c.save()
        self.wait()
        self.assertEqual(self.h.repo.settings()['accounts'],[])
        self.assertEqual(self.h.puts,[])

    def test_first_save_creates_schedule_without_edits(self):
        self.assertFalse(self.c.state['dirty'])
        self.c.save()
        self.wait()
        self.register_mock.assert_called_once_with()
        self.assertEqual(self.h.puts, [])
        self.assertIn('Automatic lockouts scheduled', self.c.state['message'])

    def test_registration_failure_can_retry_without_edits(self):
        self.register_mock.side_effect = RuntimeError('Access denied')
        self.c.save()
        self.wait()
        self.assertTrue(self.c.state['error'])
        self.assertIn('Settings saved, but scheduling failed', self.c.state['message'])
        self.register_mock.side_effect = None
        self.c.save()
        self.wait()
        self.assertFalse(self.c.state['error'])

    def test_failed_validation_does_not_register_task(self):
        with patch.object(self.h.service, 'save', side_effect=RuntimeError('Offline')):
            self.c.save()
            self.wait()
        self.register_mock.assert_not_called()
