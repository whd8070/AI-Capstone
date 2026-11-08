"""Offline tests for Claude login preflight and safe collection pipeline orchestration."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import kr_report_collection as collection


class ClaudeStatusTests(unittest.TestCase):
    @patch('kr_report_collection.claude_executable', return_value=None)
    def test_missing_cli(self, _):
        self.assertEqual(collection.claude_status()['state'], 'not_installed')

    @patch('kr_report_collection.claude_executable', return_value='/bin/claude')
    @patch('kr_report_collection.subprocess.run')
    def test_logged_out(self, run, _):
        run.return_value=Mock(returncode=1, stdout='', stderr='not logged in')
        self.assertFalse(collection.claude_status()['ready'])
        self.assertEqual(run.call_args.args[0][-2:], ['auth','status'])

    @patch('kr_report_collection.claude_executable', return_value='/bin/claude')
    @patch('kr_report_collection.subprocess.run')
    def test_logged_in_does_not_expose_email_or_token(self, run, _):
        run.return_value=Mock(returncode=0, stdout=json.dumps({'loggedIn':True,'email':'secret@example.com','token':'sensitive'}), stderr='')
        result=collection.claude_status()
        self.assertTrue(result['ready'])
        self.assertNotIn('secret@example.com', str(result))
        self.assertNotIn('sensitive', str(result))

    @patch('kr_report_collection.claude_executable', return_value='/bin/claude')
    @patch('kr_report_collection.subprocess.run', side_effect=subprocess.TimeoutExpired(['claude'], 10))
    def test_timeout_fails_closed(self, *_):
        self.assertEqual(collection.claude_status()['state'], 'check_failed')

    @patch('kr_report_collection.claude_executable', return_value='/bin/claude')
    @patch('kr_report_collection.subprocess.run')
    def test_logged_in_false_even_if_cli_exits_zero(self, run, _):
        run.return_value=Mock(returncode=0, stdout='{"loggedIn":false}', stderr='')
        self.assertFalse(collection.claude_status()['ready'])



class ClaudePathTests(unittest.TestCase):
    def test_native_installation_is_found_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            bin_dir = Path(folder) / '.local' / 'bin'
            bin_dir.mkdir(parents=True)
            binary = bin_dir / ('claude.exe' if collection.os.name == 'nt' else 'claude')
            binary.write_text('dummy', encoding='utf-8')
            binary.chmod(0o755)
            with patch('kr_report_collection.Path.home', return_value=Path(folder)):
                with patch('kr_report_collection.shutil.which', return_value=None):
                    self.assertEqual(collection.claude_executable(), str(binary))

    def test_child_path_includes_native_folder_once(self):
        with patch('kr_report_collection.claude_executable', return_value='/tmp/cli/claude'):
            with patch.dict('kr_report_collection.os.environ', {'PATH': '/usr/bin'}):
                env = collection.claude_env()
                self.assertEqual(env['PATH'].split(collection.os.pathsep)[0], '/tmp/cli')
                self.assertEqual(env['PATH'].count('/tmp/cli'), 1)



class CommandTests(unittest.TestCase):
    def test_stream_output(self):
        events=[]
        output=collection.run_stage([sys.executable,'-u','-c','print("[ok 1/1] done")'],
                                    cwd=Path.cwd(), stage='test', callback=lambda a,b: events.append((a,b)), timeout=10)
        self.assertIn('[ok 1/1]',output)
        self.assertTrue(events)

    def test_korean_windows_child_output_is_utf8(self):
        # Simulate a Windows parent locale while the Python worker writes Korean.
        observed=[]
        script = (
            'import sys; '
            'print("신규 리포트 다운로드 성공: 삼성전자 / 누락 0건"); '
            'print(sys.stdout.encoding)'
        )
        with patch.dict('kr_report_collection.os.environ', {'PYTHONIOENCODING':'cp949', 'PYTHONUTF8':'0'}):
            output=collection.run_stage(
                [sys.executable, '-u', '-c', script],
                cwd=Path.cwd(), stage='PDF 다운로드',
                callback=lambda stage,line: observed.append(line),
                timeout=10)
        self.assertIn('삼성전자', output)
        self.assertIn('신규 리포트', output)
        self.assertIn('utf-8', output.lower())
        self.assertTrue(any('삼성전자' in line for line in observed))
        self.assertNotIn('\ufffd', output)

    def test_nonzero_is_error(self):
        with self.assertRaisesRegex(RuntimeError,'종료코드 2'):
            collection.run_stage([sys.executable,'-u','-c','import sys; print("bad"); sys.exit(2)'],
                                 cwd=Path.cwd(),stage='test',timeout=10)


if __name__=='__main__':
    unittest.main()
