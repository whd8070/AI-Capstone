"""Tests of relative ranking explanations; no model or LLM access required."""
import unittest
from unittest.mock import patch
import kr_report_engine as eng


def _row(code, name, before, report, final, before_rank, after_rank, w0, w1,
         report_date=None):
    return dict(stock_code=code, company=name, mom_rank_score=before,
                pair_rank_score=before, report_rank_score=report,
                before_signal_score=before, after_signal_score=final,
                score_delta=final-before, before_rank=before_rank,
                after_rank=after_rank, rank_improvement=before_rank-after_rank,
                before_weight=w0, after_weight=w1, weight_change=w1-w0,
                report_date=report_date, implied_upside=None,
                report_target_price=None, raw_close=100.0)


class RelativeExplanationTests(unittest.TestCase):
    def setUp(self):
        # A has no report, but overtakes B and C because the cross-section moves.
        self.signal = {
            'decision_date': '2026-11-05', 'buy_date': '2026-11-06',
            'pair_share': .5, 'report_share': .5, 'report_coverage': 2,
            'scenario_before': {'mean_20d': -.02, 'q05_20d': -.06,
                                'simulated_loss_frequency': .8},
            'scenario_after': {'mean_20d': -.01, 'q05_20d': -.08,
                               'simulated_loss_frequency': .7},
            'comparison': [
                _row('000001', 'A', -1.0, 0.0, -0.5, 3, 1, .1, .3),
                _row('000002', 'B', 2.0, -3.0, -0.5, 1, 2, .5, .4, '2026-11-03'),
                _row('000003', 'C', 1.0, -3.0, -1.0, 2, 3, .4, .3, '2026-11-03')
            ]
        }

    def test_peer_crossing_does_not_depend_on_report_presence(self):
        evidence = eng.relative_rank_evidence(self.signal, limit=3)
        a = next(x for x in evidence if x['stock_code'] == '000001')
        self.assertFalse(a['report_available'])
        self.assertEqual(a['rank_before'], 3)
        self.assertEqual(a['rank_after'], 1)
        self.assertEqual(a['passed_peers_count'], 1)  # ties aren't crossings
        self.assertEqual(a['passed_peers_examples'][0]['stock_code'], '000003')
        self.assertAlmostEqual(a['individual_score_change'], .5)

    def test_local_commentary_mentions_peers_and_optimizer(self):
        text = eng.local_explanation(self.signal, [], limit=3)
        self.assertIn('상대', text)
        self.assertIn('중립', text)
        self.assertIn('공동 최적화', text)
        self.assertIn('C', text)
        self.assertIn('꼬리위험', text)

    def test_facts_include_full_universe_and_risks(self):
        facts = eng.explanation_facts(self.signal, [])
        self.assertEqual(facts['universe_size'], 3)
        self.assertEqual(len(facts['full_ranks']), 3)
        self.assertEqual(len(facts['rank_evidence']), 3)
        self.assertIn('RELATIVE', ' '.join(facts['important_limitations']))

    def test_model_choice_never_changes_weight_arrays(self):
        before = [dict(x) for x in self.signal['comparison']]
        with patch('kr_report_collection.codex_status', return_value={'ready':True}):
            with patch('kr_report_collection.load_codex_backend') as load_backend:
                load_backend.return_value.codex_explanation.return_value = '설명만 작성'
                explanation, facts = eng.llm_explanation(self.signal, [], 'codex')
        self.assertEqual(explanation, '설명만 작성')
        self.assertEqual(self.signal['comparison'], before)
        self.assertIn('rank_evidence', facts)

    def test_claude_and_codex_receive_same_structured_facts(self):
        with patch('kr_report_collection.claude_status', return_value={'ready':True}):
            with patch.object(eng, 'claude_explanation', return_value='설명'):
                text, facts = eng.llm_explanation(self.signal, [], 'claude')
        self.assertEqual(text, '설명')
        self.assertIn('full_ranks', facts)


if __name__ == '__main__':
    unittest.main()
