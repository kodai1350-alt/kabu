"""
無料マーケットデータモジュール（yfinance + DuckDuckGo）
APIキー不要、完全無料。

提供データ:
  - 日本株現在値（.T suffix）
  - マクロ指標: S&P500 / Nasdaq / VIX / USD/JPY / Nikkei225
  - ニュースヘッドライン（DuckDuckGo）
  - 過去OHLCVデータ（バックテスト用）
"""
import time
from datetime import date, timedelta
from typing import Optional

WATCHLIST_CODES = {
    "7203": "トヨタ自動車",
    "6758": "ソニーグループ",
    "9984": "ソフトバンクグループ",
    "4063": "信越化学工業",
    "8035": "東京エレクトロン",
    "6857": "アドバンテスト",
}

MACRO_TICKERS = {
    "^GSPC":  "S&P500",
    "^IXIC":  "Nasdaq",
    "^VIX":   "VIX恐怖指数",
    "JPY=X":  "USD/JPY",
    "^N225":  "日経225",
    "^TNX":   "米10年債利回り",
    "GC=F":   "金先物",
    "CL=F":   "WTI原油",
}


# ------------------------------------------------------------------ #
# 現在値
# ------------------------------------------------------------------ #

def get_current_price(code: str) -> Optional[float]:
    """日本株コードから現在値を取得 (例: "7203" → 7203.T)"""
    try:
        import yfinance as yf
        ticker = f"{code}.T"
        info = yf.Ticker(ticker).fast_info
        price = info.last_price
        return float(price) if price else None
    except Exception:
        return None


def get_macro_snapshot() -> dict:
    """主要マクロ指標の現在値を返す"""
    try:
        import yfinance as yf
        result = {}
        tickers = yf.Tickers(" ".join(MACRO_TICKERS.keys()))
        for symbol, name in MACRO_TICKERS.items():
            try:
                price = tickers.tickers[symbol].fast_info.last_price
                if price:
                    result[name] = float(price)
            except Exception:
                pass
        return result
    except Exception:
        return {}


def format_macro_snapshot() -> str:
    """マクロスナップショットを整形した文字列で返す"""
    snap = get_macro_snapshot()
    if not snap:
        return "マクロデータ取得不可"

    lines = ["📈 マーケットスナップショット"]
    for name, price in snap.items():
        if "VIX" in name:
            icon = "😱" if price > 30 else ("⚠️" if price > 20 else "😊")
            lines.append(f"  {icon} {name}: {price:.2f}")
        elif "USD/JPY" in name:
            icon = "📉" if price < 145 else ("📈" if price > 155 else "➡️")
            lines.append(f"  {icon} {name}: {price:.2f}円")
        elif "利回り" in name:
            lines.append(f"  📊 {name}: {price:.2f}%")
        elif "S&P" in name or "Nasdaq" in name or "日経" in name:
            lines.append(f"  📊 {name}: {price:,.2f}")
        else:
            lines.append(f"  📊 {name}: {price:.2f}")
    return "\n".join(lines)


def format_stocks_snapshot(codes: list) -> str:
    """監視銘柄の現在値一覧を返す"""
    try:
        import yfinance as yf
        tickers_str = " ".join(f"{c}.T" for c in codes)
        tickers = yf.Tickers(tickers_str)
        lines = ["📊 監視銘柄 現在値"]
        for code in codes:
            name = WATCHLIST_CODES.get(code, code)
            try:
                info = tickers.tickers[f"{code}.T"].fast_info
                price = info.last_price
                prev = info.previous_close
                if price and prev:
                    chg = (price - prev) / prev
                    icon = "📈" if chg > 0 else ("📉" if chg < 0 else "➡️")
                    lines.append(f"  {icon} {name}({code}): {price:,.0f}円  {chg:+.2%}")
                elif price:
                    lines.append(f"  ➡️ {name}({code}): {price:,.0f}円")
                else:
                    lines.append(f"  ⚪ {name}({code}): 取得不可")
            except Exception:
                lines.append(f"  ⚪ {name}({code}): 取得不可")
        return "\n".join(lines)
    except Exception as e:
        return f"銘柄データ取得エラー: {e}"


# ------------------------------------------------------------------ #
# ニュース（DuckDuckGo）
# ------------------------------------------------------------------ #

def get_news_ddg(query: str, max_results: int = 3) -> list[dict]:
    """DuckDuckGo ニュース検索（APIキー不要）"""
    try:
        from ddgs import DDGS
        results = list(DDGS().news(query, max_results=max_results))
        return results
    except Exception:
        return []


def format_news_ddg(queries: list[str], max_each: int = 2) -> str:
    """複数クエリのニュースをまとめて返す（Tavily代替/補完）"""
    all_items = []
    for q in queries:
        items = get_news_ddg(q, max_results=max_each)
        for item in items:
            title = item.get("title", "")
            body = item.get("body", item.get("excerpt", ""))[:150]
            all_items.append(f"- {title}: {body}")
        time.sleep(0.5)

    if not all_items:
        return "DDGニュース取得なし"
    return "\n".join(all_items)


# ------------------------------------------------------------------ #
# 過去OHLCVデータ（バックテスト用）
# ------------------------------------------------------------------ #

def get_ohlcv(code: str, period: str = "6mo") -> list[dict]:
    """
    yfinanceで日本株の過去OHLCVを取得。
    J-Quants無料プランの代替として使用可能。

    Args:
        code: 銘柄コード (例: "7203")
        period: "1mo" / "3mo" / "6mo" / "1y" / "2y"

    Returns:
        [{"date": "2026-06-22", "O": 2790, "H": 2800, "L": 2780, "C": 2786, "Vo": 1234567}, ...]
    """
    try:
        import yfinance as yf
        ticker = f"{code}.T"
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return []
        records = []
        for idx, row in hist.iterrows():
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "O": float(row["Open"]),
                "H": float(row["High"]),
                "L": float(row["Low"]),
                "C": float(row["Close"]),
                "Vo": int(row["Volume"]) if row["Volume"] else 0,
            })
        return records
    except Exception:
        return []


def get_closes(code: str, period: str = "6mo") -> list[float]:
    """終値リストを返す（backtest.py / technical.py 向け）"""
    records = get_ohlcv(code, period)
    return [r["C"] for r in records]


if __name__ == "__main__":
    print(format_macro_snapshot())
    print()
    print(format_stocks_snapshot(list(WATCHLIST_CODES.keys())))
    print()
    closes = get_closes("7203")
    print(f"7203 終値データ: {len(closes)}件  最新: {closes[-1]:,.0f}円")
