"""
네이버 증권 '종목분석 리포트' PDF 원문 수집기

종목명(예: 삼성, 하이닉스) 또는 6자리 종목코드를 주면, 기본으로 최근 1년치 리포트 PDF를
받아 날짜순으로 돌려준다. 이미 받은 PDF는 다시 받지 않는다.

CLI 사용 예:
    python naver_pdf_fetcher.py 삼성
    python naver_pdf_fetcher.py 삼성전자 하이닉스 035420 --years 2
    python naver_pdf_fetcher.py 005930 --since 2026-01-01 --until 2026-06-30

코드에서 사용 (예: 웹 서버가 요청을 받을 때마다 호출):
    from naver_pdf_fetcher import fetch_reports
    result = fetch_reports("삼성")          # 최근 1년
    result["reports"]                       # 날짜 오름차순 [{date, broker, title, pdf_path, ...}, ...]

    python naver_pdf_fetcher.py --inspect 삼성전자     # 상세 API 응답 필드 확인
    python naver_pdf_fetcher.py --backfill-meta         # 예전에 받은 행의 목표가·투자의견 채우기
    python naver_pdf_fetcher.py --universe              # universe.json 대상 기업 전체 1년치
    python naver_pdf_fetcher.py --universe --only 005930,000660 --since 2026-09-01

결과:
    data/pdf/{종목코드}/{날짜}_{nid}.pdf   ← 원문
    data/manifest.csv                       ← 받은 PDF 기록 + 목표가·투자의견 (파이프라인의 수치 기준값)

설치: pip install requests
"""
import argparse
import csv
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# 2026-11 기준: finance.naver.com/research/company_list.naver 는 stock.naver.com 으로
# 302 리다이렉트되고, 새 페이지는 JS로 아래 JSON API를 불러 목록을 그린다.
API_BASE = "https://stock.naver.com/api/stockSecurity/researches/v2"
SEARCH_URL = "https://stock.naver.com/api/autocomplete/search"
PAGE_SIZE = 20
MAX_PAGES = 100                  # 종목당 최대 2,000건
HEADERS = {"User-Agent": "Mozilla/5.0 (student capstone project, non-commercial)"}
DELAY = 1.0                      # 요청 사이 대기(초). 1초 미만으로 줄이지 말 것.

BASE_DIR = Path(__file__).resolve().parent     # 어디서 실행해도 같은 data/ 폴더 사용
UNIVERSE = BASE_DIR / "universe.json"           # 대상 기업 {종목코드: 종목명}
OUT_DIR = BASE_DIR / "data" / "pdf"
MANIFEST = BASE_DIR / "data" / "manifest.csv"
FIELDS = ["nid", "stock_code", "company", "date", "broker", "title",
          "goal_price", "opinion", "pdf_url", "pdf_path", "fetched_at"]

session = requests.Session()
session.headers.update(HEADERS)


def get(url, params=None):
    time.sleep(DELAY)
    r = session.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- 종목 찾기
def resolve_stock(query):
    """'삼성', '삼성전자', '005930' → ('005930', '삼성전자'). 못 찾으면 ValueError.
    이름으로 찾을 때: 국내 일반 종목(ETF 제외) 중 이름이 정확히 같은 것 우선, 없으면 검색 1순위."""
    query = query.strip()
    if re.fullmatch(r"\d{6}", query):
        return query, ""                       # 이름은 리포트 목록에서 채움
    params = {"q": query, "target": "stock", "size": 10, "page": 1}
    items = get(SEARCH_URL, params).json().get("result", {}).get("items", [])
    stocks = [it for it in items if it.get("nationCode") == "KOR" and not it.get("isEtf")]
    if not stocks:
        raise ValueError(f"'{query}'에 해당하는 국내 종목을 찾지 못했습니다")
    exact = [it for it in stocks if it["name"] == query]
    pick = (exact or stocks)[0]
    return pick["code"], pick["name"]


# ---------------------------------------------------------------- 목록/상세
def parse_list_page(stock_code, since, until, page):
    """목록 API 한 페이지(0부터)를 읽어 (리포트 dict 리스트, 다음 페이지 여부) 반환.
    목록 응답에는 PDF 주소가 없어서 pdf_url은 fetch_pdf_url()로 따로 채운다."""
    params = {"itemCodes": stock_code, "startDate": since, "endDate": until,
              "index": page, "size": PAGE_SIZE}
    data = get(f"{API_BASE}/company", params).json()
    rows = [{
        "nid": str(it["nid"]),
        "stock_code": stock_code,
        "company": it.get("itemName", ""),
        "title": it.get("title", ""),
        "broker": it.get("brokerName", ""),
        "date": it.get("writeDate", ""),          # 이미 YYYY-MM-DD 형식
        "pdf_url": "",
    } for it in data.get("items", [])]
    return rows, bool(data.get("hasNext"))


def fetch_detail(row):
    """상세 API에서 PDF 주소(attachUrl)·목표가(goalPrice)·투자의견(opinionText)을 가져온다.
    필드가 없으면 빈 문자열. (필드 이름은 실제 응답으로 확인할 것: --inspect 옵션)"""
    url = f"{API_BASE}/company/{row['nid']}/detail-page"
    data = get(url, {"itemCode": row["stock_code"]}).json()
    c = data.get("researchContent") or {}
    return {
        "pdf_url": c.get("attachUrl") or "",
        "goal_price": str(c.get("goalPrice") or "").replace(",", ""),
        # 2026-11 --inspect 확인: 투자의견은 opinionText("Buy"), opinionType("buy")에 있음 (opinion 키 없음)
        "opinion": (c.get("opinionText") or c.get("opinion") or "").strip(),
    }


def fetch_pdf_url(row):
    """(하위호환) PDF 주소만."""
    return fetch_detail(row)["pdf_url"]


def inspect_detail(query):
    """상세 API 응답 구조 확인용: 최근 리포트 1건의 researchContent 키와 값을 출력."""
    import json
    code, _ = resolve_stock(query)
    today = date.today().isoformat()
    rows, _ = parse_list_page(code, (date.today() - timedelta(days=90)).isoformat(), today, 0)
    if not rows:
        print("최근 90일 리포트가 없습니다"); return
    url = f"{API_BASE}/company/{rows[0]['nid']}/detail-page"
    data = get(url, {"itemCode": code}).json()
    c = data.get("researchContent") or {}
    print("top-level keys:", list(data.keys()))
    print(json.dumps({k: (v if not isinstance(v, str) or len(v) < 80 else v[:80] + "…") for k, v in c.items()},
                     ensure_ascii=False, indent=2))


def iter_reports(stock_code, since, until):
    """[since, until] 기간 리포트를 최신순으로 내보냄. 날짜 필터는 서버가 처리."""
    for page in range(MAX_PAGES):
        rows, has_next = parse_list_page(stock_code, since, until, page)
        yield from rows
        if not rows or not has_next:
            return


# ---------------------------------------------------------------- 저장
def load_manifest():
    """nid → manifest 행. 예전 형식(칼럼 부족)이면 새 칼럼을 빈 값으로 채워 파일을 다시 쓴다."""
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []
    if header != FIELDS:
        save_manifest(rows)
    return {row["nid"]: row for row in rows}


def save_manifest(rows):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def append_manifest(row):
    new_file = not MANIFEST.exists()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerow(row)


def pdf_path_for(row):
    return OUT_DIR / row["stock_code"] / f"{row['date']}_{row['nid']}.pdf"


def download(row):
    path = pdf_path_for(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = get(row["pdf_url"]).content
    if not data.startswith(b"%PDF"):           # 오류 페이지를 PDF로 저장하는 것 방지
        raise ValueError("PDF가 아닌 응답")
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------- 진입점
def fetch_reports(query, since=None, until=None, years=1, verbose=True):
    """종목 하나에 대해 기간 내 리포트 PDF를 (없는 것만) 받아서 날짜 오름차순으로 반환.

    query : 종목명 또는 6자리 코드
    since/until : 'YYYY-MM-DD'. since가 없으면 until 기준 years년 전.
    반환 : {"stock_code", "company", "since", "until", "reports": [...], "failed": [...]}
           reports의 각 항목에 pdf_path(절대경로)가 들어 있다.
    """
    until = until or date.today().isoformat()
    since = since or (date.fromisoformat(until) - timedelta(days=365 * years)).isoformat()
    code, company = resolve_stock(query)
    log = print if verbose else (lambda *a, **k: None)
    log(f"== {query} → {company or code} ({code}), {since} ~ {until}")

    manifest = load_manifest()
    reports, failed, new = [], [], 0
    for row in iter_reports(code, since, until):
        company = company or row["company"]
        if row["nid"] in manifest and pdf_path_for(row).exists():
            m = manifest[row["nid"]]
            row.update(pdf_url=m["pdf_url"], fetched_at=m["fetched_at"],
                       goal_price=m.get("goal_price", ""), opinion=m.get("opinion", ""))
        else:
            try:
                row.update(fetch_detail(row))
                if not row["pdf_url"]:
                    log(f"[skip] {row['date']} {row['broker']} | {row['title']} (PDF 첨부 없음)")
                    failed.append({**row, "error": "PDF 첨부 없음"})
                    continue
                download(row)
                row["fetched_at"] = datetime.now().isoformat(timespec="seconds")
                row["pdf_path"] = str(pdf_path_for(row).relative_to(BASE_DIR))
                append_manifest(row)
                new += 1
                log(f"[ok] {row['date']} {row['broker']} | {row['title']}")
            except Exception as e:
                log(f"[fail] nid={row['nid']}: {e}")
                failed.append({**row, "error": str(e)})
                continue
        row["pdf_path"] = str(pdf_path_for(row))
        reports.append(row)

    reports.sort(key=lambda r: (r["date"], int(r["nid"])))
    log(f"== {company} ({code}): 총 {len(reports)}건 (새로 받음 {new}건, 실패/첨부없음 {len(failed)}건)")
    return {"stock_code": code, "company": company, "since": since, "until": until,
            "reports": reports, "failed": failed}


def load_universe():
    import json
    return json.loads(UNIVERSE.read_text(encoding="utf-8"))


def fetch_universe(since=None, until=None, years=1, only=None):
    """universe.json의 기업 전체(또는 only 목록)를 순서대로 수집. 한 기업이 실패해도 다음으로 넘어간다."""
    uni = load_universe()
    codes = [c for c in uni if not only or c in only]
    summary = []
    for i, code in enumerate(codes, 1):
        print(f"\n[{i}/{len(codes)}] {uni[code]} ({code})")
        try:
            res = fetch_reports(code, since, until, years)
            summary.append((code, uni[code], len(res["reports"]), len(res["failed"])))
        except Exception as e:
            print(f"[error] {code}: {e}")
            summary.append((code, uni[code], 0, -1))
    print("\n== 수집 요약 (종목코드, 종목명, 보유 리포트, 실패/첨부없음)")
    for code, name, n, f in summary:
        print(f"  {code} {name:<12} {n:>5}건  {'오류' if f < 0 else f'{f}건'}")
    print(f"  합계 {sum(n for _, _, n, _ in summary)}건")


def backfill_meta(verbose=True):
    """manifest에서 goal_price·opinion이 비어 있는 행만 상세 API로 다시 채운다(PDF는 다시 받지 않음)."""
    rows = list(load_manifest().values())
    todo = [r for r in rows if not r.get("goal_price") and not r.get("opinion")]
    for i, r in enumerate(todo, 1):
        try:
            d = fetch_detail(r)
            r["goal_price"], r["opinion"] = d["goal_price"], d["opinion"]
            if verbose:
                print(f"[{i}/{len(todo)}] {r['date']} {r['broker']} → {r['opinion']} {r['goal_price']}")
        except Exception as e:
            print(f"[fail] nid={r['nid']}: {e}")
    save_manifest(rows)
    print(f"채움 {len(todo)}건")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="네이버 증권 종목분석 리포트 PDF 수집")
    ap.add_argument("stocks", nargs="*", help="종목명 또는 6자리 종목코드 (여러 개 가능)")
    ap.add_argument("--backfill-meta", action="store_true", help="manifest의 빈 목표가·투자의견 채우기")
    ap.add_argument("--inspect", metavar="종목", help="상세 API 응답 구조 출력(필드 이름 확인용)")
    ap.add_argument("--universe", action="store_true", help="universe.json의 대상 기업 전체 수집")
    ap.add_argument("--only", help="--universe와 함께: 일부 종목코드만 (쉼표 구분)")
    ap.add_argument("--years", type=float, default=1, help="--since가 없을 때 몇 년치 (기본 1)")
    ap.add_argument("--since", help="시작일 YYYY-MM-DD")
    ap.add_argument("--until", help="종료일 YYYY-MM-DD (기본 오늘)")
    a = ap.parse_args()
    if a.inspect:
        inspect_detail(a.inspect)
        raise SystemExit
    if a.backfill_meta:
        backfill_meta()
        raise SystemExit
    if a.universe:
        fetch_universe(a.since, a.until, a.years, set(a.only.split(",")) if a.only else None)
        raise SystemExit
    for q in a.stocks:
        try:
            res = fetch_reports(q, a.since, a.until, a.years)
        except ValueError as e:
            print(f"[error] {e}")
            continue
        for r in res["reports"]:
            print(f"  {r['date']}  {r['broker']:<10} {r.get('opinion', ''):<6} {r.get('goal_price', ''):>8}  {r['title']}")
