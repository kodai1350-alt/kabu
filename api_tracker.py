"""
API使用量トラッカー

無料枠の上限に近づいたら自動的にそのAPIをスキップし、
より安価な代替手段にフォールバックする。

使用量は api_usage.json に記録（gitignore済み）。

無料枠の目安:
  - Tavily   : 1,000リクエスト/月（無料プラン）
  - Exa      : 1,000リクエスト/月（無料プラン）
  - Groq     : 14,400リクエスト/日、500,000トークン/日（無料プラン）
"""
import json
import datetime
import os
import requests
from pathlib import Path

TRACKER_FILE = Path(__file__).parent / "api_usage.json"

# 警告しきい値（ここを超えたら警告 → 上限を超えたらSTOP）
BUDGETS = {
    "tavily": {"daily": None,  "monthly": 900,   "warn_pct": 0.8},
    "exa":    {"daily": None,  "monthly": 900,   "warn_pct": 0.8},
    "groq":   {"daily": 13000, "monthly": None,  "warn_pct": 0.85},
}

# フォールバック説明
FALLBACKS = {
    "tavily": "DuckDuckGo（無料）に切り替え",
    "exa":    "ニューススキャンをスキップ",
    "groq":   "ルールベースレポートに切り替え",
}


def _today() -> str:
    return datetime.date.today().isoformat()


def _month() -> str:
    return datetime.date.today().isoformat()[:7]


def load_usage() -> dict:
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_usage(usage: dict) -> None:
    TRACKER_FILE.write_text(
        json.dumps(usage, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record(api: str, count: int = 1) -> None:
    """API呼び出し後に使用量を記録する。"""
    usage = load_usage()
    today, month = _today(), _month()

    if api not in usage:
        usage[api] = {}

    # 日次リセット
    if usage[api].get("date") != today:
        usage[api]["daily"] = 0
        usage[api]["date"] = today

    # 月次リセット
    if usage[api].get("month") != month:
        usage[api]["monthly"] = 0
        usage[api]["month"] = month

    usage[api]["daily"]   = usage[api].get("daily", 0)   + count
    usage[api]["monthly"] = usage[api].get("monthly", 0) + count
    save_usage(usage)


def check(api: str) -> tuple[bool, str]:
    """
    このAPIを呼び出して良いかチェックする。

    Returns:
        (ok, message)
        ok=False  → STOPしてフォールバックへ
        ok=True + message に "⚠️" → 残り少ない（警告）
        ok=True + message == "ok" → 余裕あり
    """
    usage = load_usage()
    today, month = _today(), _month()
    budget = BUDGETS.get(api, {})
    api_data = usage.get(api, {})

    daily_used   = api_data.get("daily", 0)   if api_data.get("date")  == today else 0
    monthly_used = api_data.get("monthly", 0) if api_data.get("month") == month else 0

    d_lim = budget.get("daily")
    m_lim = budget.get("monthly")
    warn  = budget.get("warn_pct", 0.8)
    fb    = FALLBACKS.get(api, "スキップ")

    # 上限超過 → STOP
    if d_lim and daily_used >= d_lim:
        return False, (
            f"🚨 {api.upper()} 本日の上限到達（{daily_used}/{d_lim}回）"
            f" → {fb}"
        )
    if m_lim and monthly_used >= m_lim:
        return False, (
            f"🚨 {api.upper()} 今月の上限到達（{monthly_used}/{m_lim}回）"
            f" → {fb}"
        )

    # 警告ゾーン（80%超）
    if d_lim and daily_used >= d_lim * warn:
        remaining = d_lim - daily_used
        return True, f"⚠️ {api.upper()} 本日残り {remaining}回"
    if m_lim and monthly_used >= m_lim * warn:
        remaining = m_lim - monthly_used
        return True, f"⚠️ {api.upper()} 今月残り {remaining}回"

    return True, "ok"


def check_and_warn(api: str, discord_url: str = None) -> bool:
    """
    チェックして警告があれば Discord にも通知。
    Returns: True=使用OK / False=STOP（フォールバックへ）
    """
    ok, msg = check(api)

    if msg != "ok":
        print(f"  [{api}] {msg}")
        if discord_url and "xxxx" not in discord_url and ("⚠️" in msg or "🚨" in msg):
            try:
                requests.post(discord_url, json={"content": msg}, timeout=5)
            except Exception:
                pass

    return ok


def get_status_report() -> str:
    """全API使用状況を人間が読みやすい形式で返す"""
    usage = load_usage()
    today, month = _today(), _month()

    lines = ["📊 API残量メーター"]
    lines.append("  " + "─" * 40)

    for api, budget in BUDGETS.items():
        api_data = usage.get(api, {})
        daily   = api_data.get("daily", 0)   if api_data.get("date")  == today else 0
        monthly = api_data.get("monthly", 0) if api_data.get("month") == month else 0

        d_lim = budget.get("daily")
        m_lim = budget.get("monthly")
        warn  = budget.get("warn_pct", 0.8)

        parts = []

        if d_lim:
            pct = daily / d_lim
            bar = _bar(pct)
            status = "🚨" if pct >= 1.0 else ("⚠️" if pct >= warn else "✅")
            parts.append(f"本日 {bar} {daily}/{d_lim}  {status}")
        if m_lim:
            pct = monthly / m_lim
            bar = _bar(pct)
            status = "🚨" if pct >= 1.0 else ("⚠️" if pct >= warn else "✅")
            parts.append(f"今月 {bar} {monthly}/{m_lim}  {status}")

        if not parts:
            parts = ["無制限 ✅"]

        lines.append(f"  {api.upper():<8} " + " | ".join(parts))

    lines.append("  " + "─" * 40)
    lines.append("  🆓 yfinance / DuckDuckGo: 無制限（無料）")
    return "\n".join(lines)


def _bar(pct: float, width: int = 10) -> str:
    """使用率をバー表示に変換"""
    filled = min(width, round(pct * width))
    empty  = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(get_status_report())
