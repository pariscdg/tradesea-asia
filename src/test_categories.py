from copy import deepcopy
import unittest
import test_asia_panel as legacy
from asia_settings import identity, validate_settings
from panel_bridge import PanelBridge

class CategoryTests(unittest.TestCase):
    setUp = legacy.ServiceTests.setUp
    def allocation(self, groups):
        return dict(version=2, mode='selected', durationSeconds=43200,
                    accounts=[dict(identity(self.h.accounts[i]), category=g) for i,g in groups])

    def test_categories_use_distinct_durations(self):
        self.h.service.save(self.allocation([(0,'asia'),(1,'day')]))
        self.assertEqual(self.h.puts, [])
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual([c['end']-c['start'] for _,c in self.h.puts], [43200,86400])

    def test_empty_allocation_is_successful_noop(self):
        self.h.service.save(self.allocation([]))
        self.assertEqual(self.h.service.run(), 0)
        self.assertEqual(self.h.puts, [])

    def test_category_change_rechecks_active_lock(self):
        self.h.service.save(self.allocation([(0,'asia')]))
        self.h.service.run()
        before = deepcopy(self.h.repo.store(self.h.accounts[0]).load())
        with self.assertRaisesRegex(RuntimeError,'Duration cannot change'):
            self.h.service.save(self.allocation([(0,'day')]))
        self.assertEqual(before,self.h.repo.store(self.h.accounts[0]).load())
        self.h.service.save(self.allocation([]))
        self.assertEqual(before,self.h.repo.store(self.h.accounts[0]).load())

    def test_invalid_category_rejected(self):
        with self.assertRaises(ValueError):
            validate_settings(self.allocation([(0,'wrong')]))

    def test_bridge_migrates_legacy_selection_without_saving(self):
        self.h.service.save(self.h.selected([0],86400))
        before=self.h.repo.settings()
        data=PanelBridge(self.h.service).present(self.h.service.load())
        self.assertEqual([a['category'] for a in data['accounts']],['day',None,None])
        self.assertEqual(before,self.h.repo.settings())
