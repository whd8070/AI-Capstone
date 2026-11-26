import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kr_trace as trace


class TraceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "trace.jsonl"

    def records(self):
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]

    def test_single_record_and_stages(self):
        with trace.Trace("formula_check", {"formula": "mom"}, path=self.path) as tr:
            tr.step("diagnosis", {"share": 1.0})
            tr.finish("completed", {"accepted": True})
            tr.finish("completed")
        self.assertEqual(len(self.records()), 1)
        r = self.records()[0]
        self.assertEqual(r["output"], {"accepted": True})
        self.assertEqual(r["stages"][0]["stage"], "diagnosis")
        self.assertIsNone(r["error"])
        self.assertIn("commit", r)
        self.assertIn("latency_ms", r)

    def test_exception_and_append(self):
        with patch.dict(os.environ, {"AI_CAPSTONE_TRACE_TEXT": "0"}):
            with self.assertRaises(ValueError):
                with trace.Trace("portfolio", {}, path=self.path):
                    raise ValueError("user@example.com")
        with trace.Trace("formula", {}, path=self.path):
            pass
        a, b = self.records()
        self.assertEqual(a["status"], "error")
        self.assertEqual(a["error"]["type"], "ValueError")
        self.assertNotIn("user@example.com", self.path.read_text(encoding="utf-8"))
        self.assertNotEqual(a["request_id"], b["request_id"])

    def test_privacy_modes(self):
        with patch.dict(os.environ, {"AI_CAPSTONE_TRACE_TEXT": "0"}):
            self.assertEqual(trace.text("private input"), "[TEXT OMITTED]")
            self.assertEqual(trace.formula("0.5*mom+0.5*pair"), "0.5*mom+0.5*pair")
            self.assertEqual(trace.formula("unknown('private')"), "[TEXT OMITTED]")
        with patch.dict(os.environ, {"AI_CAPSTONE_TRACE_TEXT": "1"}):
            s = trace.text("sample@example.com 010-1234-5678 api_key=example-secret")
            for secret in ("sample@example.com", "010-1234-5678", "example-secret"):
                self.assertNotIn(secret, s)

    def test_worker_handoff(self):
        with trace.Trace("backtest", {"start": "2026-11-01"}, path=self.path) as tr:
            envelope = json.loads(json.dumps(tr.record))
            tr.defer()
        self.assertFalse(self.path.exists())
        worker = trace.Trace.resume(envelope)
        worker.path = self.path
        worker.step("signal", {"index": 1})
        worker.finish("completed", {"decisions": 1})
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["request_id"], envelope["request_id"])

    def test_logging_failure_does_not_raise(self):
        with patch.object(trace, "append", side_effect=OSError("disk error")):
            with trace.Trace("formula", {}, path=self.path) as tr:
                tr.finish("completed", {"accepted": True})
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
