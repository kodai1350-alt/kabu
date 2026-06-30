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


def _vix_label(v: float) -> str:
    if v < 15:   return "極めて低リスク / 強気相場"
    if v < 20:   return "低リスク / 平常運転"
    if v < 30:   return "警戒ゾーン / ボラ上昇"
    return "高リスク / パニック売り"

def _usdjpy_label(v: float) -> str:
    if v > 155: return f"強い円安 → 輸出株に追い風"
    if v > 145: return f"円安 → 輸出株やや有利"
    if v > 135: return f"中立"
    return f"円高 → 輸出株に逆風"

def _yield_label(v: float) -> str:
    if v > 4.5:  return "高水準 → 成長株に逆風"
    if v > 3.5:  return "やや高め → 様子見"
    return "低め → 株式に追い風"


def format_macro_snapshot() -> str:
    """マクロスナップショットを人間が読みやすい形式で返す"""
    import yfinance as yf
    import datetime
    try:
        tickers_obj = yf.Tickers(" ".join(MACRO_TICKERS.keys()))
    except Exception:
        return "マクロデータ取得不可"

    data = {}
    for symbol, name in MACRO_TICKERS.items():
        try:
            info = tickers_obj.tickers[symbol].fast_info
            price = float(info.last_price) if info.last_price else None
            prev  = float(info.previous_close) if info.previous_close else None
            if price:
                data[name] = {"price": price, "prev": prev}
        except Exception:
            pass

    if not data:
        return "マクロデータ取得不可"

    def chg_str(d):
        p, prev = d["price"], d["prev"]
        if prev and prev > 0:
            c = (p - prev) / prev * 100
            arrow = "↑" if c > 0 else ("↓" if c < 0 else "→")
            return f"{arrow}{abs(c):.1f}%"
        return ""

    JST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(JST).strftime("%H:%M")
    lines = [f"🌍 グローバル市場スナップショット（{now}現在）", ""]

    # ── 米国 ──
    lines.append("  【米国】")
    for key in ["S&P500", "Nasdaq"]:
        if key in data:
            d = data[key]
            c = chg_str(d)
            lines.append(f"    {key}: {d['price']:,.0f}  {c}")
    if "VIX恐怖指数" in data:
        v = data["VIX恐怖指数"]["price"]
        lines.append(f"    VIX: {v:.1f}  → {_vix_label(v)}")
    if "米10年債利回り" in data:
        v = data["米10年債利回り"]["price"]
        lines.append(f"    米10年債: {v:.2f}%  → {_yield_label(v)}")

    # ── 為替 ──
    lines.append("")
    lines.append("  【為替・商品】")
    if "USD/JPY" in data:
        v = data["USD/JPY"]["price"]
        c = chg_str(data["USD/JPY"])
        lines.append(f"    USD/JPY: {v:.1f}円  {c}  → {_usdjpy_label(v)}")
    for key in ["金先物", "WTI原油"]:
        if key in data:
            d = data[key]
            c = chg_str(d)
            lines.append(f"    {key}: {d['price']:,.0f}  {c}")

    # ── 日本 ──
    lines.append("")
    lines.append("  【日本】")
    if "日経225" in data:
        d = data["日経225"]
        c = chg_str(d)
        risk_on = (d["prev"] and d["price"] > d["prev"])
        mood = "上昇中" if risk_on else "下落中"
        lines.append(f"    日経225: {d['price']:,.0f}  {c}  → {mood}")

    # ── 総合判定 ──
    score = 0
    if "VIX恐怖指数" in data:
        v = data["VIX恐怖指数"]["price"]
        score += 2 if v < 15 else (1 if v < 20 else (-1 if v > 25 else 0))
    if "S&P500" in data:
        d = data["S&P500"]
        if d["prev"] and d["price"] > d["prev"]: score += 1
    if "USD/JPY" in data:
        score += 1 if data["USD/JPY"]["price"] > 145 else 0
    if "米10年債利回り" in data:
        v = data["米10年債利回り"]["price"]
        score -= 1 if v > 4.5 else 0

    if score >= 3:   mood_overall = "リスクオン 強気"
    elif score >= 1: mood_overall = "やや強気"
    elif score >= -1: mood_overall = "中立 / 様子見"
    else:            mood_overall = "リスクオフ 警戒"
    lines.append("")
    lines.append(f"  市場環境: {mood_overall}（スコア {score:+d}）")

    return "\n".join(lines)


def _chg_label(chg: float) -> str:
    if chg > 0.03:  return "大幅高"
    if chg > 0.01:  return "上昇"
    if chg > 0.002: return "小幅高"
    if chg < -0.03: return "大幅安"
    if chg < -0.01: return "下落"
    if chg < -0.002: return "小幅安"
    return "ほぼ横ばい"


# ------------------------------------------------------------------ #
# 出来高分析
# ------------------------------------------------------------------ #

def get_volume_ratio(code: str, avg_days: int = 20) -> Optional[float]:
    """
    当日出来高 ÷ 過去N日平均出来高 を返す。
    2.0 なら「平均の2倍 = 出来高急増」
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(f"{code}.T").history(period="2mo")
        if hist.empty or len(hist) < avg_days + 1:
            return None
        avg = hist["Volume"].iloc[-(avg_days + 1):-1].mean()
        today_vol = hist["Volume"].iloc[-1]
        if avg and avg > 0:
            return float(today_vol / avg)
        return None
    except Exception:
        return None


def scan_volume_signals(codes: list, rsi_threshold: float = 40,
                         volume_threshold: float = 1.5) -> list[dict]:
    """
    RSI と出来高急増の組み合わせでシグナル銘柄をスキャンする。

    Args:
        codes: 銘柄コードリスト
        rsi_threshold: RSI がこれ以下 → 売られすぎ候補
        volume_threshold: 出来高比率がこれ以上 → 急増と判定

    Returns:
        [{code, name, price, chg, rsi, volume_ratio, signal}, ...]
    """
    from technical import _rsi
    results = []
    for code in codes:
        try:
            closes = get_closes(code, period="3mo")
            if len(closes) < 30:
                continue
            rsi = _rsi(closes)
            vol_ratio = get_volume_ratio(code)
            price = closes[-1]
            prev = closes[-2] if len(closes) >= 2 else price
            chg = (price - prev) / prev if prev else 0

            # シグナル判定
            if rsi < rsi_threshold and vol_ratio and vol_ratio >= volume_threshold:
                signal = "売られすぎ＋出来高急増 → 反発候補"
            elif rsi > (100 - rsi_threshold) and vol_ratio and vol_ratio >= volume_threshold:
                signal = "買われすぎ＋出来高急増 → 利食い注意"
            elif vol_ratio and vol_ratio >= volume_threshold * 1.5:
                signal = "出来高急増 → 何か動きあり"
            else:
                signal = None

            if signal or (vol_ratio and vol_ratio >= volume_threshold):
                results.append({
                    "code": code,
                    "name": WATCHLIST_CODES.get(code, code),
                    "price": price,
                    "chg": chg,
                    "rsi": rsi,
                    "volume_ratio": vol_ratio,
                    "signal": signal,
                })
        except Exception:
            continue
    # 出来高比率が高い順に並べる
    results.sort(key=lambda x: x.get("volume_ratio") or 0, reverse=True)
    return results


def format_volume_scan(codes: list) -> str:
    """出来高スキャン結果を整形した文字列で返す"""
    hits = scan_volume_signals(codes)
    if not hits:
        return "出来高急増シグナル: 該当なし（平常の出来高）"

    lines = ["📊 出来高急増スキャン（平均比1.5倍以上）"]
    lines.append("  " + "─" * 45)
    for h in hits:
        vol_str = f"出来高 平均の{h['volume_ratio']:.1f}倍" if h["volume_ratio"] else "出来高不明"
        rsi_str = f"RSI {h['rsi']:.0f}"
        chg_str = f"{h['chg']:+.1%}"
        alert = f"  ⚡ {h['signal']}" if h["signal"] else ""
        lines.append(
            f"  {h['name']}({h['code']}):  "
            f"{h['price']:,.0f}円 {chg_str}  {rsi_str}  {vol_str}"
        )
        if alert:
            lines.append(alert)
    return "\n".join(lines)


def format_stocks_snapshot(codes: list) -> str:
    """監視銘柄の現在値を人間が読みやすい形式で返す"""
    try:
        import yfinance as yf
        tickers_str = " ".join(f"{c}.T" for c in codes)
        tickers = yf.Tickers(tickers_str)
        lines = ["📊 監視銘柄"]
        lines.append("  " + "─" * 55)
        up_count = 0
        for code in codes:
            name = WATCHLIST_CODES.get(code, code)
            short = name[:8]
            try:
                info = tickers.tickers[f"{code}.T"].fast_info
                price = info.last_price
                prev = info.previous_close
                vol_ratio = get_volume_ratio(code)
                vol_badge = ""
                if vol_ratio and vol_ratio >= 3.0:
                    vol_badge = f"  ⚡出来高{vol_ratio:.0f}倍!"
                elif vol_ratio and vol_ratio >= 1.5:
                    vol_badge = f"  出来高{vol_ratio:.1f}倍↑"
                if price and prev:
                    chg = (price - prev) / prev
                    if chg > 0: up_count += 1
                    bar = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
                    label = _chg_label(chg)
                    lines.append(
                        f"  {bar} {short}({code})  "
                        f"{price:>7,.0f}円  {chg:+.1%}  {label}{vol_badge}"
                    )
                elif price:
                    lines.append(f"  ─ {short}({code})  {price:>7,.0f}円{vol_badge}")
                else:
                    lines.append(f"  ? {short}({code})  取得不可")
            except Exception:
                lines.append(f"  ? {short}({code})  取得不可")
        lines.append("  " + "─" * 55)
        total = len(codes)
        lines.append(f"  上昇 {up_count}/{total}銘柄  下落 {total-up_count}/{total}銘柄")
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
