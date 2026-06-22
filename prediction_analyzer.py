"""
予測精度分析・学習モジュール（15:30 終了レポート用）

処理フロー:
  1. 昨日の予測を取得
  2. yfinanceで当日終値を取得して的中判定
  3. 5日前の予測があれば5日後誤差を記録
  4. Groq（または定量）でなぜ外れたか分析
  5. signal_weights.json を更新（学習）
  6. Discordレポート生成

使い方:
  from prediction_analyzer import run_analysis
  report = run_analysis()
"""
import json
import datetime
from pathlib import Path

WEIGHTS_FILE = Path(__file__).parent / "signal_weights.json"
LEARN_RATE = 0.05      # 重みの1回あたり変化量
MAX_WEIGHT = 2.0
MIN_WEIGHT = 0.2


# ------------------------------------------------------------------ #
# 重み管理
# ------------------------------------------------------------------ #

def load_weights() -> dict:
    if WEIGHTS_FILE.exists():
        return json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
    return {"rsi": 1.0, "macd": 1.0, "bb": 1.0, "trend": 1.0}


def save_weights(w: dict, reason: str = "") -> None:
    w["updated"] = datetime.date.today().isoformat()
    history = w.get("history", [])
    history.append({
        "date": w["updated"],
        "rsi": w["rsi"],
        "macd": w["macd"],
        "bb": w["bb"],
        "trend": w["trend"],
        "reason": reason,
    })
    w["history"] = history[-30:]   # 直近30件のみ保持
    WEIGHTS_FILE.write_text(
        json.dumps(w, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_weights(
    direction_correct: bool,
    dominant_signal: str,   # 最もスコアに寄与したシグナル名
    w: dict,
) -> dict:
    """
    方向が正解なら dominant_signal の重みを上げ、
    外れなら下げる（他は少しだけ平均回帰）
    """
    for key in ["rsi", "macd", "bb", "trend"]:
        if key == dominant_signal:
            delta = LEARN_RATE if direction_correct else -LEARN_RATE
        else:
            delta = -LEARN_RATE * 0.1  # 他は微小に平均回帰
        w[key] = round(max(MIN_WEIGHT, min(MAX_WEIGHT, w[key] + delta)), 3)
    return w


# ------------------------------------------------------------------ #
# 予測分析
# ------------------------------------------------------------------ #

def _analyze_prediction_llm(pred: dict, actual: float) -> str:
    """Groqでなぜ外れた/当たったかを分析"""
    try:
        from llm_client import chat
        direction_result = "的中" if pred.get("direction_ok") else "外れ"
        scenario = pred.get("in_scenario", "miss")
        scenario_label = {"bull": "強気シナリオ的中", "base": "基本シナリオ的中",
                          "bear": "弱気シナリオ的中", "miss": "全シナリオ外れ"}.get(scenario, scenario)
        price_at = pred.get("price", 0)
        slope = pred.get("trend_slope", 0)

        prompt = (
            f"{pred['name']}({pred['code']}) 予測分析\n\n"
            f"予測日: {pred['date']}\n"
            f"予測時価格: {price_at:,.0f}円\n"
            f"実際の終値: {actual:,.0f}円\n"
            f"変化: {(actual - price_at) / price_at:+.2%}\n"
            f"方向予測: {direction_result}\n"
            f"シナリオ: {scenario_label}\n"
            f"トレンド傾き: {slope:+.1f}円/日\n"
            f"シグナルスコア: {pred.get('signal_score', 0):+d}/5\n\n"
            f"なぜこの結果になったかを1〜2文で簡潔に分析してください。"
            f"（例: マクロの変化、テクニカルの限界、想定外の材料など）"
        )
        result = chat(prompt, provider="groq")
        return result if result else "分析不可"
    except Exception:
        # フォールバック: ルールベース分析
        price_at = pred.get("price", 0)
        change_pct = (actual - price_at) / price_at * 100 if price_at else 0
        slope = pred.get("trend_slope", 0)
        score = pred.get("signal_score", 0)

        if pred.get("direction_ok"):
            if abs(change_pct) > 2:
                return f"シグナル強度と実際の動きが一致（{change_pct:+.1f}%）。テクニカル分析が有効だった。"
            return f"方向は正解だが値幅は小さかった（{change_pct:+.1f}%）。"
        else:
            if score > 0 and change_pct < 0:
                return f"買いシグナルだったが下落（{change_pct:+.1f}%）。外部要因か反転シグナルの見落とし。"
            elif score < 0 and change_pct > 0:
                return f"売りシグナルだったが上昇（{change_pct:+.1f}%）。逆張り的な動きが発生。"
            return f"トレンド方向（{'+' if slope >= 0 else '-'}）と逆に動いた（{change_pct:+.1f}%）。"


def _get_dominant_signal(pred: dict) -> str:
    """予測レコードから最も影響が大きかったシグナルを特定"""
    score = pred.get("signal_score", 0)
    slope = pred.get("trend_slope", 0)
    # 簡易的にトレンド傾きが強ければtrendが支配的、そうでなければrsiを返す
    if abs(slope) > 5:
        return "trend"
    return "rsi"


# ------------------------------------------------------------------ #
# メイン分析
# ------------------------------------------------------------------ #

def fill_yesterday_actuals(preds: list) -> list:
    """昨日の予測に当日終値を埋める"""
    try:
        from market_data import get_current_price
        from prediction_log import fill_actual
        updated = []
        for p in preds:
            price = get_current_price(p["code"])
            if price:
                fill_actual(p["code"], price, date=p["date"])
                p["actual_close"] = price
                direction = price - p["price"]
                p["direction_ok"] = (direction >= 0) == (p.get("trend_slope", 0) >= 0)
                # シナリオ判定
                from prediction_log import base_in_range
                if base_in_range(price, p.get("scenario_bull", [])):
                    p["in_scenario"] = "bull"
                elif base_in_range(price, p.get("scenario_base", [])):
                    p["in_scenario"] = "base"
                elif base_in_range(price, p.get("scenario_bear", [])):
                    p["in_scenario"] = "bear"
                else:
                    p["in_scenario"] = "miss"
                p["analyzed"] = True
                updated.append(p)
    except Exception as e:
        print(f"  実績取得エラー: {e}")
    return updated


def fill_5d_actuals() -> None:
    """5日前の予測に5日後実績を埋める"""
    try:
        from prediction_log import _load, _save, fill_actual_5d
        from market_data import get_current_price
        five_days_ago = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        data = _load()
        for p in data["predictions"]:
            if p.get("date") == five_days_ago and p.get("actual_5d") is None:
                price = get_current_price(p["code"])
                if price:
                    fill_actual_5d(p["code"], price, pred_date=five_days_ago)
    except Exception:
        pass


def build_analysis_report() -> str:
    """分析結果をDiscord向けレポートにまとめる"""
    try:
        from prediction_log import get_unanalyzed_yesterday, get_accuracy_stats
    except Exception as e:
        return f"[予測分析エラー: {e}]"

    today = datetime.date.today().strftime("%Y/%m/%d")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y/%m/%d")
    lines = [f"📊 予測精度レポート【{yesterday}→{today}】", ""]

    # 昨日の予測を取得・実績を埋める
    preds = get_unanalyzed_yesterday()
    if not preds:
        # 今日の予測でも試みる（当日分析モード）
        from prediction_log import get_today_predictions
        preds = get_today_predictions()

    if not preds:
        lines.append("  昨日の予測記録なし（朝のレポートが未実行の可能性）")
        return "\n".join(lines)

    updated_preds = fill_yesterday_actuals(preds)

    # 5日前の予測に実績を埋める
    fill_5d_actuals()

    if not updated_preds:
        lines.append("  実績データ取得不可（市場非営業日？）")
        return "\n".join(lines)

    # ── 個別銘柄分析 ─────────────────────────────────────────
    lines.append("【銘柄別 予測 vs 実績】")
    w = load_weights()
    for p in updated_preds:
        actual = p.get("actual_close", 0)
        price_at = p.get("price", 0)
        change = actual - price_at
        change_pct = change / price_at * 100 if price_at else 0

        direction_icon = "✅" if p.get("direction_ok") else "❌"
        scenario = p.get("in_scenario", "miss")
        scenario_label = {
            "bull": "📈強気的中", "base": "➡️基本的中",
            "bear": "📉弱気的中", "miss": "⚠️ミス",
        }.get(scenario, scenario)

        lines.append(
            f"\n  {direction_icon} {p['name']}({p['code']})\n"
            f"     予測: {price_at:,.0f}円  実際: {actual:,.0f}円  ({change_pct:+.1f}%)\n"
            f"     シナリオ: {scenario_label}  スコア: {p.get('signal_score', 0):+d}/5"
        )

        # 分析コメント
        reason = _analyze_prediction_llm(p, actual)
        lines.append(f"     💬 {reason}")

        # 重み更新
        dominant = _get_dominant_signal(p)
        w = update_weights(p.get("direction_ok", False), dominant, w)

    # 重みを保存
    analyzed_count = len(updated_preds)
    direction_hits = sum(1 for p in updated_preds if p.get("direction_ok"))
    hit_rate = direction_hits / analyzed_count if analyzed_count else 0
    save_weights(w, reason=f"direction_rate={hit_rate:.0%} ({analyzed_count}件)")

    # ── 統計サマリー ──────────────────────────────────────────
    lines.append("")
    lines.append("【本日の精度サマリー】")
    lines.append(f"  方向的中率: {hit_rate:.0%}  ({direction_hits}/{analyzed_count})")

    scenario_hits = sum(1 for p in updated_preds if p.get("in_scenario") != "miss")
    lines.append(f"  シナリオ的中率: {scenario_hits / analyzed_count:.0%}  ({scenario_hits}/{analyzed_count})")

    # ── 累積統計 ─────────────────────────────────────────────
    stats = get_accuracy_stats(days=30)
    if stats and stats.get("total", 0) >= 3:
        lines.append("")
        lines.append("【直近30日 累積精度】")
        lines.append(f"  方向的中率: {stats['direction_rate']:.0%}  ({stats['total']}件)")
        lines.append(f"  シナリオ的中率: {stats['scenario_rate']:.0%}")
        if stats.get("abs_5d_error_pct") is not None:
            lines.append(f"  5日後予測誤差: {stats['abs_5d_error_pct']:.1f}%（絶対値平均）")

    # ── シグナル重み変化 ──────────────────────────────────────
    lines.append("")
    lines.append("【学習後シグナル重み】")
    lines.append(
        f"  RSI:{w['rsi']:.2f}  MACD:{w['macd']:.2f}  "
        f"BB:{w['bb']:.2f}  Trend:{w['trend']:.2f}"
    )

    # ── 次回予測への示唆 ─────────────────────────────────────
    dominant_w = max(["rsi", "macd", "bb", "trend"], key=lambda k: w[k])
    weakest_w = min(["rsi", "macd", "bb", "trend"], key=lambda k: w[k])
    lines.append("")
    lines.append("【次回予測への示唆】")
    lines.append(f"  📈 最も信頼できる指標: {dominant_w.upper()} (重み: {w[dominant_w]:.2f})")
    lines.append(f"  ⚠️ 要注意指標: {weakest_w.upper()} (重み: {w[weakest_w]:.2f})")

    return "\n".join(lines)


def run_analysis() -> str:
    """分析を実行してレポートを返す（close_report.pyから呼び出す）"""
    try:
        return build_analysis_report()
    except Exception as e:
        return f"[予測分析実行エラー: {e}]"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(run_analysis())
