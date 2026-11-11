"""Pure local regression tests for Windows CLI onboarding controls."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kr_cli_onboarding as onboarding


class OnboardingTests(unittest.TestCase):
    def test_status_hints(self):
        self.assertIn("설치", onboarding.onboarding_hint("codex", {"state": "not_installed"}))
        self.assertIn("로그인", onboarding.onboarding_hint("claude", {"state": "not_logged_in"}))
        self.assertIn("연결 완료", onboarding.onboarding_hint("codex", {"ready": True}))

    def test_provider_and_action_are_allowlisted(self):
        for provider, action in (("unknown", "login"), ("codex", "erase"),
                                 ("codex; rm -rf /", "install")):
            with self.assertRaises(ValueError):
                onboarding.launch_terminal(provider, action, Path.cwd())

    def test_non_windows_does_not_attempt_spawn(self):
        with patch.object(onboarding.os, "name", "posix"):
            with patch.object(onboarding.subprocess, "Popen") as start:
                with self.assertRaises(RuntimeError):
                    onboarding.launch_terminal("claude", "login", Path.cwd())
                start.assert_not_called()

    def test_windows_command_is_local_and_interactive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "connect_cli_windows.ps1").write_text("# test", encoding="utf-8")
            with patch.object(onboarding.os, "name", "nt"):
                with patch.object(onboarding.subprocess, "Popen") as start:
                    result = onboarding.launch_terminal("codex", "login", root)
                    self.assertIn("PowerShell", result)
                    args = start.call_args.args[0]
                    self.assertEqual(args[0], "powershell.exe")
                    self.assertEqual(args[-4:], ["-Provider", "codex", "-Action", "login"])
                    self.assertNotIn("stdin", start.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
