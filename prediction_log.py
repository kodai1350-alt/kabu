"""
予測ログ管理モジュール

朝の予測を prediction_log.json に保存し、
夕方に実績と照合して精度を追跡する。

保存形式:
  {
    "predictions": [
      {
        "id": "2026-06-22_7203",
        "date": "2026-06-22",
        "code": "7203",
        "name": "トヨタ自動車",
        "price": 2788,          // 予測時の現在値
        "signal_score": 1,
        "trend_slope": -8.1,
        "pred_5d": 2744,
        "scenario_bull": [2806, 2858],
        "scenario_base": [2710, 2806],
        "scenario_bear": [2692, 2710],
        "support": 2692,
        "resistance": 3392,
        // 夕方に埋める
        "actual_close": null,   // 当日終値
        "direction_ok": null,   // 方向正解 true/false
        "in_scenario": null,    // "bull"/"base"/"bear"/"miss"
        "analyzed": false,
        // 5日後に埋める
        "actual_5d": null,
        "pred_5d_error_pct": null,
      }
    ]
  }
"""
import json
import datetime
from pathlib import Path

LOG_FILE = Path(__file__).parent / "prediction_log.json"


def _load() -> dict:
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    return {"predictions": []}


def _save(data: dict) -> None:
    LOG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_prediction(
    code: str,
    name: str,
    price: float,
    signal_score: int,
    trend_slope: float,
    pred_5d: float,
    scenario_bull: list,
    scenario_base: list,
    scenario_bear: list,
    support: float,
    resistance: float,
    date: str = None,
) -> None:
    """朝の予測を保存"""
    today = date or datetime.date.today().isoformat()
    record_id = f"{today}_{code}"

    data = _load()
    # 同じIDが既にあれば上書き
    data["predictions"] = [p for p in data["predictions"] if p["id"] != record_id]
    data["predictions"].append({
        "id": record_id,
        "date": today,
        "code": code,
        "name": name,
        "price": price,
        "signal_score": signal_score,
        "trend_slope": trend_slope,
        "pred_5d": pred_5d,
        "scenario_bull": scenario_bull,
        "scenario_base": scenario_base,
        "scenario_bear": scenario_bear,
        "support": support,
        "resistance": resistance,
        "actual_close": None,
        "direction_ok": None,
        "in_scenario": None,
        "analyzed": False,
        "actual_5d": None,
        "pred_5d_error_pct": None,
    })
    _save(data)


def fill_actual(code: str, actual_close: float, date: str = None) -> None:
    """当日終値を記録し、方向・シナリオ的中を判定"""
    today = date or datetime.date.today().isoformat()
    record_id = f"{today}_{code}"

    data = _load()
    for p in data["predictions"]:
        if p["id"] == record_id:
            p["actual_close"] = actual_close
            # 方向正解チェック（トレンド傾きと実際の方向を比較）
            direction = actual_close - p["price"]
            predicted_direction = p["trend_slope"]
            p["direction_ok"] = (direction >= 0) == (predicted_direction >= 0)

            # シナリオ的中チェック
            bull = p["scenario_bull"]
            base = p["scenario_base"]
            bear = p["scenario_bear"]
            if bull and base_in_range(actual_close, bull):
                p["in_scenario"] = "bull"
            elif base and base_in_range(actual_close, base):
                p["in_scenario"] = "base"
            elif bear and base_in_range(actual_close, bear):
                p["in_scenario"] = "bear"
            else:
                p["in_scenario"] = "miss"
            p["analyzed"] = True
            break
    _save(data)


def fill_actual_5d(code: str, actual_5d: float, pred_date: str) -> None:
    """5日後の実績を記録（pred_dateは予測を出した日）"""
    record_id = f"{pred_date}_{code}"
    data = _load()
    for p in data["predictions"]:
        if p["id"] == record_id:
            p["actual_5d"] = actual_5d
            if p["pred_5d"] and p["pred_5d"] != 0:
                p["pred_5d_error_pct"] = (actual_5d - p["pred_5d"]) / p["pred_5d"] * 100
            break
    _save(data)


def base_in_range(value: float, rng: list) -> bool:
    if not rng or len(rng) < 2:
        return False
    return min(rng) <= value <= max(rng)


def get_recent_predictions(days: int = 30) -> list:
    """直近N日の予測レコードを返す"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    data = _load()
    return [p for p in data["predictions"] if p.get("date", "") >= cutoff]


def get_today_predictions() -> list:
    today = datetime.date.today().isoformat()
    data = _load()
    return [p for p in data["predictions"] if p.get("date") == today]


def get_unanalyzed_yesterday() -> list:
    """昨日の未分析予測を返す（夕方バッチ用）"""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    data = _load()
    return [
        p for p in data["predictions"]
        if p.get("date") == yesterday and not p.get("analyzed")
    ]


def get_accuracy_stats(days: int = 30) -> dict:
    """直近N日の精度統計を集計"""
    preds = [p for p in get_recent_predictions(days) if p.get("analyzed")]
    if not preds:
        return {}

    direction_hits = sum(1 for p in preds if p.get("direction_ok"))
    scenario_hits = sum(1 for p in preds if p.get("in_scenario") in ("bull", "base", "bear"))
    scenario_dist = {"bull": 0, "base": 0, "bear": 0, "miss": 0}
    for p in preds:
        scenario_dist[p.get("in_scenario", "miss")] = \
            scenario_dist.get(p.get("in_scenario", "miss"), 0) + 1

    error_5d = [p["pred_5d_error_pct"] for p in preds if p.get("pred_5d_error_pct") is not None]

    return {
        "total": len(preds),
        "direction_rate": direction_hits / len(preds),
        "scenario_rate": scenario_hits / len(preds),
        "scenario_dist": scenario_dist,
        "avg_5d_error_pct": sum(error_5d) / len(error_5d) if error_5d else None,
        "abs_5d_error_pct": sum(abs(e) for e in error_5d) / len(error_5d) if error_5d else None,
    }
