"""Offline regression tests for display, missing-report handling and fail-closed verification."""
import unittest
from unittest.mock import patch

import kr_report_engine as engine
import kr_report_verification as verification


def example():
    return {
        "stock_code": "005930", "company": "샘플기업",
        "before_rank": 8, "after_rank": 5,
        "before_weight": .015003, "after_weight": .102345,
        "weight_change": .087342, "rank_improvement": 3,
        "mom_rank_score": .2, "pair_rank_score": .3,
        "report_date": None,
        "implied_upside": None, "before_signal_score": .134,
        "after_signal_score": .346, "report_rank_score": 0.0,
    }


def explanation():
    return "\n\n".join(
        f"## {x}\n\n테스트된 포트폴리오 수치와 자료를 설명합니다. (portfolio)"
        for x in verification.REQUIRED_SECTIONS
    )


class DisplayTests(unittest.TestCase):
    def test_held_only_and_pct_precision(self):
        a = example()
        b = dict(a, stock_code="000660", company="비편입", after_weight=0.0)
        rows = engine.display_portfolio_rows([b, a], held_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["반영 후 비중"], "10.23%")
        self.assertEqual(rows[0]["반영 전 비중"], "1.50%")
        self.assertEqual(rows[0]["비중 변화"], "+8.73%p")
        self.assertEqual(rows[0]["리포트 날짜"], "없음")
        self.assertEqual(len(engine.display_portfolio_rows([b, a], held_only=False)), 2)
        self.assertEqual(a["after_weight"], .102345)  # raw calculations untouched

    def test_only_holdings_are_sent_to_explainer(self):
        a = example()
        b = dict(a, stock_code="000660", company="비편입", after_weight=0.0)
        source = dict(
            comparison=[a, b], decision_date="2026-01-08", buy_date="2026-01-09",
            pair_share=.5, report_share=.4, report_coverage=0,
            scenario_before={"mean_20d":.0123, "q05_20d":-.03211,
                             "simulated_loss_frequency":.54321},
            scenario_after={"mean_20d":.0234, "q05_20d":-.0444,
                            "simulated_loss_frequency":.48998},
        )
        facts = engine.explanation_facts(source, [])
        self.assertEqual(facts["holding_count"], 1)
        self.assertEqual(facts["holdings"][0]["weight_after_pct"], "10.23%")
        report = engine.local_explanation(source, [])
        self.assertIn("## 선정 이유", report)
        self.assertIn("## 불확실성", report)
        self.assertIn("유효한 개별 리포트가 없습니다", report)
        self.assertNotIn("비편입", report)
        self.assertEqual(verification.local_status(report)["status"], "LOCAL_RULE_ONLY")


class LatencyRegressionTests(unittest.TestCase):
    def test_ai_regeneration_reuses_existing_portfolio_without_inference(self):
        import tempfile
        from pathlib import Path
        source = {
            'comparison': [example()], 'compact': [],
            'decision_date': '2026-01-08', 'buy_date': '2026-01-09',
        }
        verified = {
            'explanation': explanation(), 'agent_used': 'codex',
            'agent_warning': None, 'analysis_facts': {'holdings': []},
            'verification': {'status': 'PASS', 'claim_count': 5},
        }
        with tempfile.TemporaryDirectory() as folder:
            source['path'] = Path(folder)
            with patch.object(engine, 'build_portfolio_explanation',
                              return_value=verified) as builder, \
                 patch('kr_pair_cpu.load_market', side_effect=AssertionError('must not re-fetch')), \
                 patch('kr_pair_cpu.load_model', side_effect=AssertionError('must not reload')):
                output = engine.regenerate_portfolio_explanation(source, 'codex')
            builder.assert_called_once()
            self.assertEqual(output['agent_used'], 'codex')
            self.assertEqual((Path(folder) / 'explanation.txt').read_text('utf-8'),
                             verified['explanation'])
            self.assertEqual(source['comparison'], output['comparison'])


class CompactInputTests(unittest.TestCase):
    def test_all_holdings_remain_but_unneeded_report_details_are_removed(self):
        facts = {
            'decision_date': '2026-01-08', 'buy_date': '2026-01-09',
            'pair_share_pct': '50.00%', 'report_share_pct': '50.00%',
            'holdings': [
                {'stock_code': '005930', 'company': '첫 종목', 'weight_after_pct': '12.34%',
                 'rank_before': 1, 'rank_after': 2, 'report_available': True,
                 'passed_peers_examples': [{'company': '이웃A', 'stock_code': '000001'},
                                            {'company': '이웃B', 'stock_code': '000002'},
                                            {'company': '이웃C', 'stock_code': '000003'}]},
                {'stock_code': '000660', 'company': '두 번째 종목',
                 'weight_after_pct': '8.76%', 'report_available': False},
            ],
            'report_records': [
                {'nid': str(k), 'stock_code': '005930', 'date': f'2026-01-0{k}',
                 'broker': f'증권사{k}', 'target_price': 100000,
                 'rationale': [{'claim': f'근거{i}', 'page': i} for i in range(10)],
                 'risks': [{'claim': f'위험{i}', 'page': i} for i in range(10)],
                 'earnings_forecast': [{'very_large': 'x' * 10000}]}
                for k in range(1, 5)
            ],
            'all_stock_ranks': [{'stock_code': str(k), 'rank_after': k}
                                for k in range(44)],
            'scenario': {'after': {'mean_pct': '1.23%'}},
        }
        condensed = verification.compact_agent_facts(facts)
        self.assertEqual(len(condensed['holdings']), 2)
        self.assertEqual(len(condensed['report_records']), 2)
        self.assertEqual(len(condensed['report_records'][0]['rationale']), 2)
        self.assertEqual(len(condensed['report_records'][0]['risks']), 2)
        self.assertEqual(len(condensed['holdings'][0]['passed_peers_examples']), 2)
        self.assertNotIn('all_stock_ranks', condensed)
        self.assertNotIn('earnings_forecast', condensed['report_records'][0])
        self.assertEqual(condensed['holdings'][0]['weight_after_pct'], '12.34%')
        self.assertEqual(condensed['holdings'][1]['report_available'], False)
        import json
        self.assertLess(len(json.dumps(condensed)), len(json.dumps(facts)) / 3)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.facts = {"holdings": [{"stock_code": "005930"}],
                      "report_records": [{"nid": "123"}]}

    def test_all_claims_are_checked_and_grounded(self):
        def runner(backend, markdown, facts, claims):
            return {"claims": [
                {"claim_id": x["claim_id"], "verdict": "pass",
                 "reason_code": "OK", "evidence_refs": ["portfolio"]}
                for x in claims]}
        r = verification.verify(explanation(), self.facts, backend="codex", runner=runner)
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["claim_count"], 5)
        self.assertEqual(r["content_sha256"], verification.digest(explanation()))

    def test_reject_is_fail_closed(self):
        def runner(backend, markdown, facts, claims):
            return {"claims": [{"claim_id": x["claim_id"], "verdict": "reject",
                                "reason_code": "HALLUCINATION", "evidence_refs": []}
                               for x in claims]}
        self.assertEqual(verification.verify(
            explanation(), self.facts, backend="codex", runner=runner)["status"], "FAIL")

    def test_missing_claim_verdict_blocks_publication(self):
        def runner(backend, markdown, facts, claims):
            return {"claims": []}
        r = verification.verify(explanation(), self.facts, backend="codex", runner=runner)
        self.assertIn("INCOMPLETE_OR_DUPLICATED_CLAIM_VERDICTS", r["errors"])

    def test_unknown_reference_blocks_publication(self):
        def runner(backend, markdown, facts, claims):
            return {"claims": [
                {"claim_id": x["claim_id"], "verdict": "pass",
                 "reason_code": "OK", "evidence_refs": ["report:made-up"]}
                for x in claims]}
        r = verification.verify(explanation(), self.facts, backend="codex", runner=runner)
        self.assertEqual(r["status"], "FAIL")

    def test_verifier_exception_is_not_pass(self):
        def runner(*args):
            raise TimeoutError("mock")
        r = verification.verify(explanation(), self.facts, backend="claude", runner=runner)
        self.assertEqual(r["status"], "FAIL")
        self.assertTrue(any("VERIFIER_ERROR" in x for x in r["errors"]))

    def test_required_sections_and_decimal_precision(self):
        self.assertTrue(any("MISSING_SECTION" in x for x in
                            verification.rule_errors("## 선정 이유\n\n문장")))
        self.assertIn("DECIMALS_OVER_TWO_PLACES",
                      verification.rule_errors(explanation() + "\n\n비중 1.234%"))


if __name__ == "__main__":
    unittest.main()
