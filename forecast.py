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

    # 学習済み重みを読み込む
    try:
        from prediction_analyzer import load_weights
        w = load_weights()
    except Exception:
        w = {"rsi": 1.0, "macd": 1.0, "bb": 1.0, "trend": 1.0}

    rsi = _rsi(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    macd_line, sig_line = _macd(closes)
    trend = _linear_regression(closes)
    s_rsi   = _rsi_signal(rsi)   * w.get("rsi", 1.0)
    s_macd  = _macd_signal(macd_line, sig_line) * w.get("macd", 1.0)
    s_bb    = _bb_signal(closes[-1], bb_upper, bb_mid, bb_lower) * w.get("bb", 1.0)
    s_trend = _trend_signal(trend.get("slope", 0), closes[-1]) * w.get("trend", 1.0)
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

    buffer = current * 0.005  # 最低0.5%幅を保証
    base_lo = max(support, pred5 - weekly_move * 0.5 + bias)
    base_hi = min(resistance, pred5 + weekly_move * 0.5 + bias)
    if base_hi <= base_lo: base_hi = base_lo + buffer * 2
    bull_lo = base_hi
    bull_hi = max(bull_lo + buffer, min(resistance, base_hi + weekly_move * 0.4 + abs(bias)))
    bear_hi = base_lo
    bear_lo = min(bear_hi - buffer, max(support * 0.99, base_lo - weekly_move * 0.4 - abs(bias)))

    if score >= 2:   p_bull, p_base, p_bear = 40, 45, 15
    elif score <= -2: p_bull, p_base, p_bear = 15, 45, 40
    else:            p_bull, p_base, p_bear = 25, 50, 25

    confidence = min(5, max(1, 3 + round(r2 * 2)))
    trend_word = f"{'上昇' if slope > 0 else '下落'}中（{slope:+.0f}円/日）"
    signal_word = "買い" if score > 0 else ("売り" if score < 0 else "中立")
    return (
        f"強気シナリオ: {bull_lo:,.0f}〜{bull_hi:,.0f}円（確率{p_bull}%）\n"
        f"基本シナリオ: {base_lo:,.0f}〜{base_hi:,.0f}円（確率{p_base}%）\n"
        f"弱気シナリオ: {bear_lo:,.0f}〜{bear_hi:,.0f}円（確率{p_bear}%）\n"
        f"確信度: {confidence}/5\n"
        f"根拠: トレンド{trend_word}・{signal_word}シグナル・下値目処{support:,.0f}円"
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

    pred5  = trend.get("pred_5d", current)
    pred10 = trend.get("pred_10d", current)
    chg5   = (pred5  - current) / current * 100
    chg10  = (pred10 - current) / current * 100

    # テクニカル指標を平易な言葉に変換
    det = signal.get("details", {})
    rsi_val = det.get("rsi", (50, 0))[0]
    if rsi_val > 70:   rsi_comment = f"RSI {rsi_val:.0f} → 買われすぎ注意"
    elif rsi_val < 30: rsi_comment = f"RSI {rsi_val:.0f} → 売られすぎ（反発期待）"
    elif rsi_val > 60: rsi_comment = f"RSI {rsi_val:.0f} → やや過熱"
    elif rsi_val < 40: rsi_comment = f"RSI {rsi_val:.0f} → 割安圏"
    else:              rsi_comment = f"RSI {rsi_val:.0f} → 中立ゾーン"

    bb_s = det.get("bb", (0, 0))[1]
    if bb_s >= 2:   bb_comment = "価格が下限付近 → 反発しやすい"
    elif bb_s <= -2: bb_comment = "価格が上限付近 → 利食いに注意"
    else:            bb_comment = "価格がバンド中央付近"

    macd_s = det.get("macd", (0, 0))[1]
    tr_s   = det.get("trend", (0, 0))[1]
    macd_comment = "上昇モメンタム" if macd_s > 0 else "下降モメンタム"
    trend_comment = f"直近30日: {slope:+.0f}円/日ペースで{'上昇中' if slope > 0 else '下落中'}"

    lines = [f"🔮 来週の予測【{name}（{code}）】", ""]
    lines.append(f"  現在値: {current:,.0f}円")
    lines.append(f"  トレンド方向: {trend_label}")
    lines.append(f"    └ {trend_comment}")
    lines.append("")
    lines.append(f"  テクニカル判定: {signal['label']}")
    lines.append(f"    └ {rsi_comment}")
    lines.append(f"    └ {macd_comment} / {bb_comment}")
    lines.append("")
    if sr:
        support    = sr["support"]
        resistance = sr["resistance"]
        sup_pct    = (support    - current) / current * 100
        res_pct    = (resistance - current) / current * 100
        lines.append(f"  価格の壁")
        lines.append(f"    サポート(下値目処): {support:,.0f}円  今より{sup_pct:.1f}%")
        lines.append(f"    レジスタンス(上値目処): {resistance:,.0f}円  今より{res_pct:+.1f}%")
        lines.append("")
    lines.append(f"  トレンド予測（統計モデル）")
    lines.append(f"    5日後: {pred5:,.0f}円  （{chg5:+.1f}%）")
    lines.append(f"    10日後: {pred10:,.0f}円  （{chg10:+.1f}%）")
    lines.append("")
    lines.append("  シナリオ別 来週の値幅予想")
    llm_pred = _llm_price_forecast(code, name, current, signal, trend, sr, context)
    for ln in llm_pred.splitlines():
        if "シナリオ" in ln or "確信度" in ln or "根拠" in ln:
            # 確率・価格帯をパース表示
            import re
            m = re.search(r"(強気|基本|弱気)シナリオ[：:]\s*([\d,]+)[〜～～-]([\d,]+).*?（確率(\d+)%）", ln)
            if m:
                label_s = m.group(1)
                lo = float(m.group(2).replace(",", ""))
                hi = float(m.group(3).replace(",", ""))
                prob = m.group(4)
                lo_pct = (lo - current) / current * 100
                hi_pct = (hi - current) / current * 100
                icon = "↑" if label_s == "強気" else ("↓" if label_s == "弱気" else "→")
                lines.append(
                    f"    {icon} {label_s}シナリオ ({prob}%):  "
                    f"{lo:,.0f}〜{hi:,.0f}円  "
                    f"[{lo_pct:+.1f}%〜{hi_pct:+.1f}%]"
                )
            elif "確信度" in ln or "根拠" in ln:
                lines.append(f"    {ln.strip()}")
        else:
            lines.append(f"    {ln.strip()}")

    # 予測をログに保存（的中率学習のため）
    try:
        from prediction_log import save_prediction
        # シナリオ範囲をパース
        scenario_bull, scenario_base, scenario_bear = _parse_scenarios(llm_pred, current)
        save_prediction(
            code=code, name=name, price=current,
            signal_score=signal["score"],
            trend_slope=trend.get("slope", 0),
            pred_5d=trend.get("pred_5d", current),
            scenario_bull=scenario_bull,
            scenario_base=scenario_base,
            scenario_bear=scenario_bear,
            support=sr.get("support", current * 0.93),
            resistance=sr.get("resistance", current * 1.07),
        )
    except Exception:
        pass

    return "\n".join(lines)


def _parse_scenarios(llm_text: str, current: float) -> tuple:
    """LLMテキストからシナリオ価格帯を抽出（失敗時はルールベース値を返す）"""
    import re
    results = {}
    for key in ["強気", "基本", "弱気"]:
        pattern = rf"{key}シナリオ[：:]\s*([\d,]+)[〜～～-]([\d,]+)"
        m = re.search(pattern, llm_text)
        if m:
            lo = float(m.group(1).replace(",", ""))
            hi = float(m.group(2).replace(",", ""))
            results[key] = [lo, hi]
    bull = results.get("強気", [current * 1.02, current * 1.05])
    base = results.get("基本", [current * 0.99, current * 1.02])
    bear = results.get("弱気", [current * 0.95, current * 0.99])
    return bull, base, bear


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
