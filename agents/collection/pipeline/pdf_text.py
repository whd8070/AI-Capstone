"""PDF → 페이지별 텍스트 (리포트당 1회 변환 후 data/text/{nid}.json 에 캐시).
토큰 절감: 컴플라이언스 고지 페이지 제거, 연속 공백·빈 줄 압축."""
import json
import re
from pathlib import Path

import pymupdf

from .config import ROOT, TEXT_DIR

SKIP_PAGE = re.compile(r"Compliance Notice|투자의견\s*분류|투자등급\s*(관련|비율)|당사는\s*동\s*자료", re.I)


def _compact(t):
    t = re.sub(r"[ \t\u3000]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def get_pages(nid, pdf_path):
    """페이지별 텍스트 리스트. 고지 페이지는 ''로 두어 페이지 번호를 유지한다."""
    cache = TEXT_DIR / f"{nid}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["pages"]
    path = Path(pdf_path)
    if not path.is_absolute():
        path = ROOT / path
    with pymupdf.open(path) as doc:
        pages = [_compact(p.get_text("text")) for p in doc]
    pages = ["" if SKIP_PAGE.search(t) else t for t in pages]
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"nid": nid, "pages": pages}, ensure_ascii=False), encoding="utf-8")
    return pages


def build_input(pages, n):
    return "\n\n".join(f"[p{i + 1}]\n{t}" for i, t in enumerate(pages[:n]) if t)
