"""Explicit local-terminal onboarding for optional Claude/Codex CLI providers.

No authentication tokens or CLI output are read by this module. The terminal
is started only after a human clicks an install/login button on web page 3.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

PROVIDERS = {"codex", "claude"}
ACTIONS = {"install", "login"}


def launch_terminal(provider: str, action: str, project: Path) -> str:
    if provider not in PROVIDERS or action not in ACTIONS:
        raise ValueError("Unknown CLI provider/action")
    if os.name != "nt":
        raise RuntimeError("One-click CLI setup is supported on local Windows only.")
    project = Path(project).resolve()
    script = project / "connect_cli_windows.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Windows CLI onboarding script not found: {script}")
    # Explicit argument allowlist; never pass arbitrary user-provided commands.
    args = [
        "powershell.exe", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-Provider", provider, "-Action", action,
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(
        args,
        cwd=str(project),
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    return "별도의 PowerShell 창을 열었습니다. 해당 창에서 진행 상황과 로그인을 확인한 뒤 이 페이지로 돌아오세요."


def onboarding_hint(provider: str, state: dict) -> str:
    if state.get("ready"):
        return "연결 완료. 리포트 구조화와 포트폴리오 설명에 선택할 수 있습니다."
    status = state.get("state")
    if status == "not_installed":
        return "CLI가 설치되지 않았습니다. 아래 설치 버튼부터 누르세요."
    if status == "not_logged_in":
        return "CLI는 설치됐지만 로그인되지 않았습니다. 로그인 버튼을 누르세요."
    return "연결 확인이 실패했습니다. 아래 안내를 확인하고 연결을 다시 검사하세요."
