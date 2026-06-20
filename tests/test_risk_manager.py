"""risk_manager.py の単体テスト"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

from risk_manager import RiskManager, STATE_FILE


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """各テスト前にstateファイルを一時ディレクトリに隔離"""
    tmp_state = tmp_path / "risk_state.json"
    monkeypatch.setattr("risk_manager.STATE_FILE", tmp_state)
    yield tmp_state
    if tmp_state.exists():
        tmp_state.unlink()


# ------------------------------------------------------------------ #
# ポジションサイズチェック
# ------------------------------------------------------------------ #

def test_position_size_ok():
    rm = RiskManager()
    ok, msg = rm.check_before_order("7203", 140_000, 1_000_000)  # 14%
    assert ok
    assert msg == "OK"


def test_position_size_over():
    rm = RiskManager()
    ok, msg = rm.check_before_order("7203", 160_000, 1_000_000)  # 16%
    assert not ok
    assert "ポジションサイズオーバー" in msg


# ------------------------------------------------------------------ #
# 日次損失チェック
# ------------------------------------------------------------------ #

def test_daily_loss_not_reached():
    rm = RiskManager()
    rm._state["today_pnl_pct"] = -0.04  # -4%（上限-5%未満）
    ok, msg = rm.check_before_order("7203", 100_000, 1_000_000)
    assert ok


def test_daily_loss_reached():
    rm = RiskManager()
    rm._state["today_pnl_pct"] = -0.05  # 上限到達
    ok, msg = rm.check_before_order("7203", 100_000, 1_000_000)
    assert not ok
    assert "最大損失" in msg


# ------------------------------------------------------------------ #
# 連敗ストップ
# ------------------------------------------------------------------ #

def test_consecutive_loss_stop():
    rm = RiskManager()
    balance = 1_000_000
    # 1回あたり-1.4%×3回 = -4.2%（日次上限-5%未満）で3連敗を作る
    rm.record_trade_result("7203", -0.014, balance)
    rm.record_trade_result("6758", -0.014, balance)
    rm.record_trade_result("9984", -0.014, balance)  # 3連敗

    ok, msg = rm.check_before_order("4063", 100_000, balance)
    assert not ok
    assert "自動停止" in msg


def test_win_resets_consecutive_loss():
    rm = RiskManager()
    balance = 1_000_000
    rm.record_trade_result("7203", -0.03, balance)
    rm.record_trade_result("7203", -0.03, balance)
    rm.record_trade_result("7203", +0.05, balance)  # 勝ちでリセット

    assert rm.consecutive_losses == 0


# ------------------------------------------------------------------ #
# ストップロス判定
# ------------------------------------------------------------------ #

def test_stop_loss_hit():
    rm = RiskManager()
    hit, msg = rm.check_stop_loss("7203", entry_price=3400, current_price=3100)
    assert hit  # -8.8% → SLヒット
    assert "SLヒット" in msg


def test_stop_loss_not_hit():
    rm = RiskManager()
    hit, msg = rm.check_stop_loss("7203", entry_price=3400, current_price=3300)
    assert not hit  # -2.9% → SL未到達


# ------------------------------------------------------------------ #
# 日次リセット
# ------------------------------------------------------------------ #

def test_daily_reset(clean_state):
    # 昨日の状態を書き込む
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    state = {
        "date": yesterday,
        "last_reset": yesterday,
        "today_pnl": -50000,
        "today_pnl_pct": -0.05,
        "consecutive_losses": 2,
        "consecutive_wins": 0,
        "cooldown_until": None,
        "trades_today": [{"ticker": "7203"}],
    }
    clean_state.write_text(json.dumps(state), encoding="utf-8")

    rm = RiskManager()
    assert rm._state["date"] == datetime.now().strftime("%Y-%m-%d")
    assert rm._state["today_pnl"] == 0.0
    assert rm._state["trades_today"] == []
    assert rm._state["consecutive_losses"] == 2  # 連敗は引き継ぎ


# ------------------------------------------------------------------ #
# ステータスレポート
# ------------------------------------------------------------------ #

def test_status_report():
    rm = RiskManager()
    report = rm.status_report()
    assert "リスクマネージャー" in report
    assert "本日損益" in report
