"""파이프라인 설정. 경로는 이 프로젝트 폴더(report-fetcher) 기준."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.csv"           # naver_pdf_fetcher.py 결과 = 수치·메타데이터 기준값
TEXT_DIR = DATA / "text"                   # PDF→텍스트 캐시 (리포트당 1회만 변환)
OUT_DIR = DATA / "out"
REPORTS_JSONL = OUT_DIR / "reports.jsonl"  # 리포트 1건 = JSON 1줄
USAGE_CSV = OUT_DIR / "usage.csv"          # 호출별 토큰·비용 기록
BY_DATE_DIR = OUT_DIR / "by_date"          # export 결과: 종목/날짜별 묶음

PROMPT_VERSION = "report_extract_v1"
SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
SCHEMA_FILE = Path(__file__).parent / "schemas" / "report_v1.json"

# 입력 페이지 정책
BASE_PAGES = 2        # 기본: 앞 2쪽
EXPAND_PAGES = 4      # 플래그가 서면 1회만 4쪽으로 재추출
MIN_CHARS = 800       # 앞 페이지가 이보다 짧으면 커버 페이지 의심

# ---- Claude Code 백엔드 (Max 구독 로그인 사용)
CLAUDE_MODEL = os.environ.get("RF_CLAUDE_MODEL", "haiku")      # haiku / sonnet / opus
# 토큰 절감용 추가 플래그. 기본: 도구 전부 끔(텍스트는 stdin으로 넘기므로 도구 불필요).
# claude --help 로 지원 여부 확인 후, 문제 있으면 환경변수로 바꿀 수 있음. 예) RF_CLAUDE_EXTRA="" (끄기)
CLAUDE_EXTRA = os.environ.get("RF_CLAUDE_EXTRA", '--tools ""')
CLAUDE_TIMEOUT = 240

# ---- Claude API 백엔드 (선택, 대량 처리용)
API_MODEL = os.environ.get("RF_API_MODEL", "claude-haiku-5-5")

# ---- 대상 기업
UNIVERSE_FILE = ROOT / "universe.json"

# ---- 사용량 안전장치
CONFIRM_OVER = 20          # 이보다 많은 건수를 돌리려면 실행 전에 확인(y/N)을 받음 (--yes로 생략)
HANDOFF_DIR = DATA / "handoff"
CONSENSUS_WINDOW_DAYS = 90 # 컨센서스: 기준일 이전 N일 안의 증권사별 최신 리포트
