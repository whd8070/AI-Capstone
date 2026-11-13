import unittest

import numpy as np

from kr_formula import FormulaError, blend, parse, rank_z, score, used_variables

MOM = np.array([1.0, -1.0, 0.5, -0.5, 0.0])
PAIR = np.array([-1.0, 1.0, 0.0, 0.5, -0.5])
REPORT = np.array([0.0, 1.5, -1.5, 0.0, 0.7])


class AllowedTests(unittest.TestCase):
    def test_default_blend_matches_manual(self):
        got = score("0.5*(0.5*mom + 0.5*pair) + 0.5*report", MOM, PAIR, REPORT)
        want = rank_z(0.5 * (0.5 * MOM + 0.5 * PAIR) + 0.5 * REPORT)
        np.testing.assert_allclose(got, want)

    def test_functions_and_compare(self):
        for f in ["where(abs(report) > 0.8, report, mom)", "min(mom, pair, report)",
                  "clip(mom, -1, 1) + tanh(pair) - pos(-report)", "rank_z(mom*pair) + sign(report)",
                  "-mom ** 2 + pair / 2", "max(mom, 0.3*report) * (pair >= 0)"]:
            self.assertEqual(score(f, MOM, PAIR, REPORT).shape, (5,), f)

    def test_blend_keeps_scale_and_centers(self):
        raw = 0.5 * (0.5 * MOM + 0.5 * PAIR) + 0.5 * REPORT
        got = blend("0.5*(0.5*mom + 0.5*pair) + 0.5*report", MOM, PAIR, REPORT)
        np.testing.assert_allclose(got, raw - raw.mean())
        shifted = blend("min(mom, pair) + 3", MOM, PAIR, REPORT)
        self.assertAlmostEqual(float(shifted.mean()), 0.0)

    def test_used_variables(self):
        self.assertEqual(used_variables("mom + 2*report"), ["mom", "report"])


class RejectedTests(unittest.TestCase):
    def test_code_injection_is_rejected(self):
        attacks = [
            "__import__('os').system('calc')", "open('C:/x.txt','w')", "mom.__class__",
            "(lambda: mom)()", "[m for m in mom]", "exec('1')", "eval('mom')", "mom if pair else report",
            "getattr(mom, 'x')", "mom; pair", "import os", "f'{mom}'", "'abc'", "mom[0]",
            "print(mom)", "abs(mom, key=1)", "abs.__call__(mom)", "mom @ pair", "mom << 2", "mom and pair",
            "(mom := 1)", "True + mom", "{'a': mom}", "mom < pair < report", "mom == pair",
        ]
        for a in attacks:
            with self.assertRaises(FormulaError, msg=a):
                parse(a)

    def test_limits(self):
        for bad in ["", "   ", "1 + 2", "mom ** 0.5", "mom ** 9", "mom ** pair", "mom * 1e9",
                    "mom" + " + mom" * 100, "abs(" * 20 + "mom" + ")" * 20, "clip(mom, 0)", "unknown(mom)"]:
            with self.assertRaises(FormulaError, msg=bad):
                parse(bad)

    def test_bad_results(self):
        for bad in ["mom / 0", "mom / (pair - pair)", "0 * mom", "where(mom > 99, 1, 2)", "100*mom + report"]:
            with self.assertRaises(FormulaError, msg=bad):
                score(bad, MOM, PAIR, REPORT)


if __name__ == "__main__":
    unittest.main()
