"""
EDINET API（金融庁）による日本株 適時開示・有価証券報告書取得
無料・登録不要 / https://disclosure2.edinet-fsa.go.jp/
"""
import os
import requests
from datetime import date, timedelta

EDINET_BASE = "https://disclosure2.edinet-fsa.go.jp/api/v2"


def _edinet_headers() -> dict:
    api_key = os.getenv("EDINET_DB_API_KEY", "")
    if api_key and "xxx" not in api_key:
        return {"Ocp-Apim-Subscription-Key": api_key}
    return {}


def _is_configured() -> bool:
    api_key = os.getenv("EDINET_DB_API_KEY", "")
    return bool(api_key) and "xxx" not in api_key


def get_disclosures(target_date: str | None = None, days: int = 3) -> list:
    """指定日前後のEDINET提出書類一覧を返す（有価証券報告書・適時開示等）"""
    if not _is_configured():
        return []

    results = []
    headers = _edinet_headers()

    for i in range(days):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            r = requests.get(
                f"{EDINET_BASE}/documents.json",
                headers=headers,
                params={"date": d, "type": 2},
                timeout=10,
            )
            if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                docs = r.json().get("results", [])
                results.extend(docs)
        except Exception:
            pass

    return results


def disclosure_scan(company_name: str, edinet_code: str | None = None) -> str:
    """企業名またはEDINETコードで適時開示を検索"""
    docs = get_disclosures(days=5)
    if not docs:
        return f"[EDINET] {company_name}: 直近5日間の提出書類なし（またはAPI未設定）"

    hits = []
    for doc in docs:
        filer = doc.get("filerName", "")
        doc_type = doc.get("docDescription", "")
        submitted = doc.get("submitDateTime", "")[:10]

        if edinet_code and doc.get("edinetCode") == edinet_code:
            hits.append(f"  {submitted} [{doc_type}] {filer}")
        elif company_name.replace("株式会社", "").strip() in filer:
            hits.append(f"  {submitted} [{doc_type}] {filer}")

    if not hits:
        return f"[EDINET] {company_name}: 直近5日間の開示なし"

    return f"[EDINET] {company_name} 適時開示:\n" + "\n".join(hits[:5])


# 銘柄コード → EDINETコード対応表（主要銘柄）
CODE_TO_EDINET = {
    "7203": "E02144",  # トヨタ自動車
    "6758": "E01777",  # ソニーグループ
    "9984": "E05080",  # ソフトバンクグループ
    "4063": "E01038",  # 信越化学工業
    "8035": "E01777",  # 東京エレクトロン
    "6857": "E01921",  # アドバンテスト
}


def scan_watchlist(watchlist: list) -> str:
    """監視リスト全銘柄のEDINET開示をまとめてスキャン"""
    if not _is_configured():
        return "[EDINET未設定] APIキーを取得して EDINET_DB_API_KEY に設定してください\n登録: https://disclosure2.edinet-fsa.go.jp/"

    output = []
    for stock in watchlist:
        code = stock.get("code", "")
        name = stock.get("name", "")
        edinet_code = CODE_TO_EDINET.get(code)
        result = disclosure_scan(name, edinet_code)
        output.append(result)
    return "\n".join(output)
