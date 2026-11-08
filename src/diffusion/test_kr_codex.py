"""Offline Codex CLI integration tests; no login, API calls or PDF downloads."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kr_report_collection import load_codex_backend, codex_status


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.backend = load_codex_backend()
        self.schema = {
            "type": "object", "additionalProperties": False,
            "required": ["target_price", "rationale"],
            "properties": {
                "target_price": {"type": ["number", "null"]},
                "rationale": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["page"], "properties": {"page": {"type": "integer"}}
                }}
            }
        }

    def test_login_missing_cli(self):
        with patch.object(self.backend, "codex_executable", return_value=None):
            self.assertEqual(self.backend.codex_status()["state"], "not_installed")

    def test_login_uses_existing_cli_without_exposing_account(self):
        def fake_run(argv, **kwargs):
            self.assertEqual(argv[-2:], ["login", "status"])
            return subprocess.CompletedProcess(argv, 0, stdout="Signed in as someone@example.com")
        with patch.object(self.backend, "codex_executable", return_value="/fake/codex"):
            with patch.object(self.backend.subprocess, "run", side_effect=fake_run):
                status = self.backend.codex_status()
        self.assertTrue(status["ready"])
        self.assertNotIn("someone@example.com", repr(status))

    def test_structured_output_pipeline(self):
        def fake_run(argv, **kwargs):
            self.assertIn("--sandbox", argv)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
            self.assertIn("--output-schema", argv)
            self.assertEqual(argv[-1], "-")
            self.assertEqual(kwargs["input"], "보고서")
            result_path = Path(argv[argv.index("--output-last-message") + 1])
            result_path.write_text(json.dumps({
                "target_price": 123000.0, "rationale": [{"page": 1}]
            }), encoding="utf-8")
            return subprocess.CompletedProcess(
                argv, 0,
                stdout='{"type":"turn.completed","usage":{"input_tokens":43,"output_tokens":11}}',
                stderr="")
        with patch.object(self.backend, "codex_executable", return_value="/fake/codex"):
            with patch.object(self.backend.subprocess, "run", side_effect=fake_run):
                answer, usage = self.backend.codex_json("보고서", self.schema)
        self.assertEqual(answer["target_price"], 123000.0)
        self.assertEqual(usage["input_tokens"], 43)
        self.assertIsNone(usage["cost_usd"])

    def test_nested_schema_violation_is_rejected(self):
        def fake_run(argv, **kwargs):
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(json.dumps({
                "target_price": None, "rationale": [{"page": "not integer"}]
            }), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        with patch.object(self.backend, "codex_executable", return_value="/fake/codex"):
            with patch.object(self.backend.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "스키마 검증 실패"):
                    self.backend.codex_json("text", self.schema)


if __name__ == "__main__":
    unittest.main()
