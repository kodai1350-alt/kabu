import os
import math
import time
from datetime import date, timedelta
import requests

JQUANTS_V2_BASE = "https://api.jquants.com/v2"


def _get_headers() -> dict | None:
    api_key = os.getenv("JQUANTS_API_KEY", "")
    if not api_key or "xxx" in api_key:
        return None
    return {"x-api-key": api_key}


def _fetch_ohlcv(code: str, headers: dict, days: int = 80) -> list:
    from_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    r = requests.get(
        f"{JQUANTS_V2_BASE}/equities/bars/daily",
        headers=headers,
        params={"code": code, "from": from_date},
        timeout=10,
    )
    if r.status_code == 400 and "subscription" in r.text:
        # サブスク期限外 → 利用可能な直近データで再試行（レートリミット回避のため待機）
        time.sleep(3)
        r = requests.get(
            f"{JQUANTS_V2_BASE}/equities/bars/daily",
            headers=headers,
            params={"code": code},
            timeout=10,
        )
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(
            f"{JQUANTS_V2_BASE}/equities/bars/daily",
            headers=headers,
            params={"code": code},
            timeout=10,
        )
    r.raise_for_status()
    return r.json().get("data", [])


def _ema(prices: list, period: int) -> float:
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def _rsi(closes: list, period: int = 14) -> float:
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _bollinger(closes: list, period: int = 20) -> tuple:
    if len(closes) < period:
        c = closes[-1]
        return c, c, c
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((p - mid) ** 2 for p in window) / period)
    return mid + 2 * std, mid, mid - 2 * std


def _macd(closes: list) -> tuple:
    if len(closes) < 35:
        return 0.0, 0.0
    macd_vals = []
    for i in range(8, -1, -1):
        end = len(closes) - i
        window = closes[max(0, end - 26):end]
        if len(window) < 26:
            macd_vals.append(0.0)
        else:
            macd_vals.append(_ema(window[-26:], 12) - _ema(window[-26:], 26))
    return macd_vals[-1], _ema(macd_vals, 9)


def _technical_from_closes(code: str, closes: list) -> str:
    if len(closes) < 20:
        return f"[{code}] データ不足（{len(closes)}日分）"
    last = closes[-1]
    rsi = _rsi(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    macd_line, signal = _macd(closes)
    histogram = macd_line - signal
    rsi_label = "買われすぎ⚠️" if rsi > 70 else "売られすぎ🔥" if rsi < 30 else "中立"
    bb_label = "上限超え⚠️" if last > bb_upper else "下限付近🔥" if last < bb_lower else "バンド内"
    macd_label = "ゴールデンクロス📈" if histogram > 0 else "デッドクロス📉"
    return (
        f"【{code} テクニカル】\n"
        f"  現在値 : {last:,.0f}円\n"
        f"  RSI(14): {rsi:.1f} → {rsi_label}\n"
        f"  MACD  : {macd_line:+.2f} / Signal: {signal:+.2f} → {macd_label}\n"
        f"  BB    : 上{bb_upper:,.0f} / 中{bb_mid:,.0f} / 下{bb_lower:,.0f} → {bb_label}"
    )


def technical_scan(code: str) -> str:
    # yfinance（無料・リアルタイム・キー不要）
    try:
        from market_data import get_closes
        closes = get_closes(code, period="3mo")
        if closes and len(closes) >= 20:
            return _technical_from_closes(code, closes)
    except Exception:
        pass

    # J-Quants（フォールバック）
    headers = _get_headers()
    if headers is None:
        return f"[データ取得不可] {code} のテクニカル分析をスキップ"

    try:
        quotes = _fetch_ohlcv(code, headers)
        if not quotes:
            return f"[{code}] データなし"
        closes = [float(q["C"]) for q in quotes if q.get("C") is not None]
        return _technical_from_closes(code, closes)
    except Exception as e:
        return f"[{code}] テクニカル取得エラー: {e}"
