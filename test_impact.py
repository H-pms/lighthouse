import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import impact


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.guard = patch.object(impact, 'LEDGER', Path(self.temp.name) / 'impact_ledger.json')
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.items = [{'_no': 1, 'link': 'https://example.com/source', 'date': '2026-09-12'}]
        self.card = {'id': '', 'event': '가상 수출 제한', 'refs': [1], 'status': '미확인',
                     'update': '신규 가설', 'steps': [dict(effect='조달 지연 가능', refs=[1],
                     condition='대체 조달이 어려울 때', benefit='대체 공급자', harm='수입 기업',
                     alternative='허가 예외로 공급 유지', observe='통관량과 납기', timing='시행 이후') ]}

    def payload(self):
        return json.dumps({'cards': [self.card], 'unknowns': ['재고 수준 미확인']})

    def test_persists_updates_and_revision(self):
        report = impact.finalize(self.payload(), self.items, '2026-09-12')
        self.assertIn('반대 경로', report)
        cid = next(iter(impact.previous()['cards']))
        self.card.update(id=cid, status='지연', update='지연 가능성 갱신')
        impact.finalize(self.payload(), self.items, '2026-09-12')
        self.assertEqual(len(impact.previous()['cards']), 1)
        revisions = json.loads((impact.LEDGER.parent / 'impacts/2026-09-12.json').read_text(encoding='utf-8'))
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0]['cards'][cid]['status'], '미확인')

    def test_bad_evidence_does_not_write(self):
        self.card['steps'][0]['refs'] = [999]
        with self.assertRaises(ValueError):
            impact.finalize(self.payload(), self.items, '2026-09-12')
        self.assertFalse(impact.LEDGER.exists())

    def test_missing_branch_rejected(self):
        del self.card['steps'][0]['alternative']
        with self.assertRaises(ValueError):
            impact.validate(self.payload(), self.items)

    def test_invented_prior_id_rejected(self):
        self.card['id'] = 'invented'
        with self.assertRaises(ValueError):
            impact.finalize(self.payload(), self.items, '2026-09-12')

    def test_maximum_three_steps(self):
        self.card['steps'] *= 4
        with self.assertRaises(ValueError):
            impact.validate(self.payload(), self.items)


if __name__ == '__main__':
    unittest.main()
