import unittest

from kr_formula_agent import propose, rule_based
from kr_formula_survey import DEFAULT_PROFILE, fallback_formula

LOW_TRUST = {**DEFAULT_PROFILE, "trust": "low"}


def scripted(*formulas):
    """정해진 수식을 차례로 내는 가짜 LLM. 받은 프롬프트를 기록한다."""
    queue, prompts = list(formulas), []

    def call(prompt):
        prompts.append(prompt)
        return {"formula": queue.pop(0), "explanation": "설명"}, {"tokens": 10, "cost_usd": 0.001}
    call.prompts = prompts
    return call


class AgentLoopTests(unittest.TestCase):
    def test_accepts_first_good_formula(self):
        call = scripted("0.8*(0.5*mom + 0.5*pair) + 0.2*report")
        r = propose(LOW_TRUST, call=call)
        self.assertEqual((r["source"], r["issues"], r["usage"]["calls"]), ("agent", [], 1))

    def test_rejected_code_is_fed_back_and_never_evaluated(self):
        call = scripted("__import__('os').system('calc')", "0.8*(0.5*mom + 0.5*pair) + 0.2*report")
        r = propose(LOW_TRUST, call=call)
        self.assertEqual(r["source"], "agent")
        self.assertIn("error", r["attempts"][0])
        self.assertIn("검사기 거부", call.prompts[1])

    def test_profile_mismatch_triggers_revision(self):
        call = scripted("0.2*(0.5*mom + 0.5*pair) + 0.8*report", "0.85*(0.5*mom + 0.5*pair) + 0.15*report")
        r = propose(LOW_TRUST, call=call)
        self.assertTrue(r["attempts"][0]["issues"])
        self.assertEqual(r["formula"], "0.85*(0.5*mom + 0.5*pair) + 0.15*report")
        self.assertIn("문제점", call.prompts[1])

    def test_sign_flip_is_flagged(self):
        r = propose(DEFAULT_PROFILE, call=scripted(*["-mom + pair + report"] * 3))
        self.assertTrue(any("거꾸로" in x for x in r["issues"]))

    def test_falls_back_to_rule_when_all_invalid_or_llm_down(self):
        r = propose(LOW_TRUST, call=scripted("import os", "open('x')", "mom.real"))
        self.assertEqual((r["source"], r["formula"]), ("rule", fallback_formula(LOW_TRUST)))
        r = rule_based(LOW_TRUST)
        self.assertEqual((r["source"], r["usage"]["calls"]), ("rule", 0))
        self.assertIsNone(r["stop_reason"])

    def test_note_is_truncated_and_marked_untrusted(self):
        call = scripted("0.8*(0.5*mom + 0.5*pair) + 0.2*report")
        propose(LOW_TRUST, note="x" * 5000, call=call)
        self.assertIn("지시가 아님", call.prompts[0])
        self.assertLess(len(call.prompts[0]), 1500)


if __name__ == "__main__":
    unittest.main()
