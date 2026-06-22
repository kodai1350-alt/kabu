"""
未来予測モジュール（完全無料）

機能:
  1. 線形回帰トレンド（傾き・目標値）
  2. シグナル統合スコア (-5〜+5)
  3. サポート/レジスタンス水準
  4. LLM価格帯予測（Groq、失敗時はルールベースフォールバック）

使い方:
  from forecast import forecast_stock
  report = forecast_stock("7203", "トヨタ自動車")
"""
import math
from typing import Optional


# ------------------------------------------------------------------ #
# 1. 線形回帰トレンド
# ------------------------------------------------------------------ #

def _linear_regression(closes: list, window: int = 30) -> dict:
    data = closes[-window:]
    n = len(data)
    if n < 5:
        return {}
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(data) / n
    num = sum((xs[i] - mean_x) * (data[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return {}
    slope = num / den
    intercept = mean_y - slope * mean_x
    ss_res = sum((data[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((data[i] - mean_y) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {
        "slope": slope,
        "r2": r2,
        "pred_5d": slope * (n + 4) + intercept,
        "pred_10d": slope * (n + 9) + intercept,
        "current": data[-1],
    }


# ------------------------------------------------------------------ #
# 2. シグナル統合スコア
# ------------------------------------------------------------------ #

def _rsi_signal(rsi: float) -> int:
    if rsi < 30:   return +2
    if rsi < 45:   return +1
    if rsi > 70:   return -2
    if rsi > 55:   return -1
    return 0


def _macd_signal(macd: float, signal: float) -> int:
    hist = macd - signal
    if hist > 0 and macd > 0:  return +2
    if hist > 0:                return +1
    if hist < 0 and macd < 0:  return -2
    return -1


def _bb_signal(price: float, upper: float, mid: float, lower: float) -> int:
    bb_pct = (price - lower) / (upper - lower) if upper != lower else 0.5
    if bb_pct < 0.2:   return +2
    if bb_pct < 0.4:   return +1
    if bb_pct > 0.8:   return -2
    if bb_pct > 0.6:   return -1
    return 0


def _trend_signal(slope: float, current: float) -> int:
    if current == 0:
        return 0
    pct = slope / current * 100
    if pct > 0.3:   return +2
    if pct > 0.1:   return +1
    if pct < -0.3:  return -2
    if pct < -0.1:  return -1
    return 0


def calc_signal_score(closes: list) -> dict:
    from technical import _rsi, _bollinger, _macd
    if len(closes) < 30:
        return {"score": 0, "label": "データ不足", "details": {}}
    rsi = _rsi(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    macd_line, sig_line = _macd(closes)
    trend = _linear_regression(closes)
    s_rsi   = _rsi_signal(rsi)
    s_macd  = _macd_signal(macd_line, sig_line)
    s_bb    = _bb_signal(closes[-1], bb_upper, bb_mid, bb_lower)
    s_trend = _trend_signal(trend.get("slope", 0), closes[-1])
    total = s_rsi + s_macd + s_bb + s_trend
    score = max(-5, min(5, round(total * 5 / 8)))
    if score >= 3:   label = "強い買いシグナル 🔥"
    elif score >= 1: label = "買いシグナル 📈"
    elif score <= -3: label = "強い売りシグナル ⚠️"
    elif score <= -1: label = "売りシグナル 📉"
    else:            label = "中立 ➡️"
    return {
        "score": score,
        "label": label,
        "details": {
            "rsi": (rsi, s_rsi),
            "macd": (macd_line, s_macd),
            "bb": (closes[-1], s_bb),
            "trend": (trend.get("slope", 0), s_trend),
        },
    }


# ------------------------------------------------------------------ #
# 3. サポート/レジスタンス水準
# ------------------------------------------------------------------ #

def calc_support_resistance(closes: list, window: int = 60) -> dict:
    data = closes[-window:]
    if len(data) < 10:
        return {}
    current = data[-1]
    high = max(data)
    low = min(data)
    recent = data[-20:]
    r_high = max(recent)
    r_low = min(recent)
    prev_h = max(data[-6:-1]) if len(data) >= 6 else high
    prev_l = min(data[-6:-1]) if len(data) >= 6 else low
    prev_c = data[-2] if len(data) >= 2 else current
    pivot = (prev_h + prev_l + prev_c) / 3
    r1 = 2 * pivot - prev_l
    s1 = 2 * pivot - prev_h
    r2 = pivot + (prev_h - prev_l)
    s2 = pivot - (prev_h - prev_l)
    candidates_r = sorted([r_high, r1, r2, high], reverse=True)
    candidates_s = sorted([r_low, s1, s2, low])
    resistance = next((v for v in candidates_r if v > current * 1.005), r_high)
    support = next((v for v in candidates_s if v < current * 0.995), r_low)
    return {
        "support": support,
        "resistance": resistance,
        "pivot": pivot,
        "range_pct": (resistance - support) / current * 100,
    }


# ------------------------------------------------------------------ #
# 4. シナリオ生成（ルールベース）
# ------------------------------------------------------------------ #

def _rule_based_forecast(current: float, signal: dict, trend: dict, sr: dict) -> str:
    score = signal.get("score", 0)
    slope = trend.get("slope", 0)
    pred5 = trend.get("pred_5d", current)
    r2 = trend.get("r2", 0.3)
    support = sr.get("support", current * 0.93)
    resistance = sr.get("resistance", current * 1.07)

    weekly_move = abs(slope) * 5 + current * 0.02
    bias = score * current * 0.005

    base_lo = max(support, pred5 - weekly_move * 0.5 + bias)
    base_hi = min(resistance, pred5 + weekly_move * 0.5 + bias)
    bull_lo = base_hi
    bull_hi = min(resistance, base_hi + weekly_move * 0.4 + abs(bias))
    bear_lo = max(support, base_lo - weekly_move * 0.4 - abs(bias))
    bear_hi = base_lo

    if score >= 2:   p_bull, p_base, p_bear = 40, 45, 15
    elif score <= -2: p_bull, p_base, p_bear = 15, 45, 40
    else:            p_bull, p_base, p_bear = 25, 50, 25

    confidence = min(5, max(1, 3 + round(r2 * 2)))
    return (
        f"強気シナリオ: {bull_lo:,.0f}〜{bull_hi:,.0f}円（確率{p_bull}%）\n"
        f"基本シナリオ: {base_lo:,.0f}〜{base_hi:,.0f}円（確率{p_base}%）\n"
        f"弱気シナリオ: {bear_lo:,.0f}〜{bear_hi:,.0f}円（確率{p_bear}%）\n"
        f"確信度: {confidence}/5\n"
        f"根拠: トレンド{slope:+.0f}円/日・スコア{score:+d}・S={support:,.0f}/R={resistance:,.0f}"
    )


def _llm_price_forecast(
    code: str, name: str, current: float,
    signal: dict, trend: dict, sr: dict, context: str = ""
) -> str:
    """Groqで価格帯シナリオ生成（失敗時はルールベースにフォールバック）"""
    try:
        from llm_client import chat
        score = signal.get("score", 0)
        slope = trend.get("slope", 0)
        pred5 = trend.get("pred_5d", current)
        support = sr.get("support", current * 0.92)
        resistance = sr.get("resistance", current * 1.08)
        prompt = (
            f"あなたは日本株の定量アナリストです。以下のデータから{name}({code})の"
            f"1週間後（5営業日後）の価格帯を予測してください。\n\n"
            f"現在値: {current:,.0f}円\n"
            f"シグナルスコア: {score:+d}/5（{signal.get('label', '')}）\n"
            f"トレンド傾き: {slope:+.1f}円/日\n"
            f"回帰予測5日後: {pred5:,.0f}円\n"
            f"サポート: {support:,.0f}円  レジスタンス: {resistance:,.0f}円\n"
            f"追加情報: {context[:300] if context else 'なし'}\n\n"
            f"## 出力形式（必ずこの形式で）\n"
            f"強気シナリオ: X,XXX〜X,XXX円（確率XX%）\n"
            f"基本シナリオ: X,XXX〜X,XXX円（確率XX%）\n"
            f"弱気シナリオ: X,XXX〜X,XXX円（確率XX%）\n"
            f"確信度: X/5\n"
            f"根拠: （1〜2文で）"
        )
        result = chat(prompt, provider="groq")
        if result and "シナリオ" in result:
            return result
    except Exception:
        pass
    return _rule_based_forecast(current, signal, trend, sr)


# ------------------------------------------------------------------ #
# メイン: forecast_stock
# ------------------------------------------------------------------ #

def forecast_stock(
    code: str,
    name: str,
    closes: Optional[list] = None,
    context: str = "",
) -> str:
    """
    銘柄の未来予測レポートを返す。

    Args:
        code: 銘柄コード (例: "7203")
        name: 銘柄名
        closes: 終値リスト（省略時はyfinanceから自動取得）
        context: マクロ/ニュースの追加文脈

    Returns:
        予測レポート文字列
    """
    if closes is None:
        try:
            from market_data import get_closes
            closes = get_closes(code, period="6mo")
        except Exception:
            closes = []

    if len(closes) < 30:
        return f"[{name}({code})] データ不足で予測不可"

    current = closes[-1]
    trend = _linear_regression(closes)
    signal = calc_signal_score(closes)
    sr = calc_support_resistance(closes)

    slope = trend.get("slope", 0)
    r2 = trend.get("r2", 0)
    if abs(slope) < current * 0.001:
        trend_label = "横ばい ➡️"
    elif slope > 0:
        trend_label = f"{'強い' if r2 > 0.6 else ''}上昇トレンド 📈"
    else:
        trend_label = f"{'強い' if r2 > 0.6 else ''}下降トレンド 📉"

    lines = [f"🔮 未来予測【{name}({code})】", ""]
    lines.append(f"  トレンド: {trend_label}���30日回帰 {slope:+.1f}円/日, R²={r2:.2f}）")
    lines.append(f"  5日後予測: {trend.get('pred_5d', 0):,.0f}円  "
                 f"10日後: {trend.get('pred_10d', 0):,.0f}円")
    lines.append("")
    lines.append(f"  シグナルスコア: {signal['score']:+d}/5  {signal['label']}")
    det = signal.get("details", {})
    if det:
        rsi_val, rsi_s = det.get("rsi", (50, 0))
        macd_val, macd_s = det.get("macd", (0, 0))
        _, bb_s = det.get("bb", (0, 0))
        _, tr_s = det.get("trend", (0, 0))
        lines.append(f"    RSI={rsi_val:.0f}({rsi_s:+d})  "
                     f"MACD={macd_val:+.0f}({macd_s:+d})  "
                     f"BB({bb_s:+d})  Trend({tr_s:+d})")
    lines.append("")
    if sr:
        lines.append(f"  サポート: {sr['support']:,.0f}円  "
                     f"レジスタンス: {sr['resistance']:,.0f}円  "
                     f"（値幅: {sr['range_pct']:.1f}%）")
        lines.append("")
    lines.append("  🤖 AIシナリオ予測（1週間）")
    llm_pred = _llm_price_forecast(code, name, current, signal, trend, sr, context)
    for ln in llm_pred.splitlines():
        lines.append(f"    {ln}")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    code = sys.argv[1] if len(sys.argv) > 1 else "7203"
    names = {
        "7203": "トヨタ自動車", "6758": "ソニーグループ",
        "9984": "ソフトバンクグループ", "4063": "信越化学工業",
        "8035": "東京エレクトロン", "6857": "アドバンテスト",
    }
    print(forecast_stock(code, names.get(code, code)))
