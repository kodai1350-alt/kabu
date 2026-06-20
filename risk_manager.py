"""
リスク管理モジュール
- 1銘柄ポジション上限チェック
- 1日最大損失チェック
- 連敗による自動停止
- ストップロス判定
状態は risk_state.json に永続化（日次リセット対応）
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "risk_state.json"


class RiskManager:
    MAX_SINGLE_POSITION = 0.15   # 1銘柄15%以下
    STOP_LOSS_PCT = -0.08         # -8%でストップロス
    MAX_DAILY_LOSS = -0.05        # 1日-5%で全停止
    MAX_CONSECUTIVE_LOSS = 3      # 3連敗で24h停止
    COOLDOWN_HOURS = 24           # 連敗停止時間

    def __init__(self):
        self._state = self._load_state()
        self._maybe_reset_daily()

    # ------------------------------------------------------------------ #
    # 外部API
    # ------------------------------------------------------------------ #

    def check_before_order(self, ticker: str, amount: float, balance: float) -> tuple[bool, str]:
        """注文前の全チェック。(ok: bool, reason: str) を返す"""
        checks = [
            self._check_position_size(amount, balance),
            self._check_daily_loss(),
            self._check_cooldown(),
        ]
        for ok, reason in checks:
            if not ok:
                return False, reason
        return True, "OK"

    def check_stop_loss(self, ticker: str, entry_price: float, current_price: float) -> tuple[bool, str]:
        """現在値がストップロスラインを下回っているか判定"""
        if entry_price <= 0:
            return False, "エントリー価格が無効"
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= self.STOP_LOSS_PCT:
            return True, f"SLヒット: {pnl_pct:.1%}（閾値 {self.STOP_LOSS_PCT:.1%}）"
        return False, f"損益: {pnl_pct:.1%}"

    def record_trade_result(self, ticker: str, pnl_pct: float, balance: float) -> None:
        """取引結果を記録し、状態を更新する"""
        pnl_amount = balance * pnl_pct

        # 日次損益を更新
        self._state["today_pnl"] += pnl_amount
        self._state["today_pnl_pct"] = self._state["today_pnl"] / max(balance, 1)

        # 連勝・連敗カウント更新
        if pnl_pct < 0:
            self._state["consecutive_losses"] += 1
            self._state["consecutive_wins"] = 0
            if self._state["consecutive_losses"] >= self.MAX_CONSECUTIVE_LOSS:
                cooldown_until = (datetime.now() + timedelta(hours=self.COOLDOWN_HOURS)).isoformat()
                self._state["cooldown_until"] = cooldown_until
                print(f"⚠️  {self.MAX_CONSECUTIVE_LOSS}連敗 → {self.COOLDOWN_HOURS}h自動停止 (解除: {cooldown_until[:16]})")
        else:
            self._state["consecutive_losses"] = 0
            self._state["consecutive_wins"] += 1
            self._state["cooldown_until"] = None

        # 取引履歴（当日分）
        self._state["trades_today"].append({
            "ticker": ticker,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_amount": round(pnl_amount, 0),
            "timestamp": datetime.now().isoformat(),
        })

        self._save_state()

    def status_report(self) -> str:
        """現在のリスク状態サマリーを返す"""
        s = self._state
        cooldown = self._cooldown_remaining()
        lines = [
            "【リスクマネージャー状態】",
            f"  本日損益  : {s['today_pnl_pct']:+.2%} ({s['today_pnl']:+,.0f}円)",
            f"  連敗回数  : {s['consecutive_losses']}回 / 上限{self.MAX_CONSECUTIVE_LOSS}回",
            f"  本日取引  : {len(s['trades_today'])}件",
            f"  停止状態  : {'冷却中 残り' + cooldown if cooldown else '稼働中'}",
            f"  最終更新  : {s.get('last_reset', 'N/A')[:16]}",
        ]
        return "\n".join(lines)

    @property
    def today_loss(self) -> float:
        return self._state["today_pnl_pct"]

    @property
    def consecutive_losses(self) -> int:
        return self._state["consecutive_losses"]

    # ------------------------------------------------------------------ #
    # 内部チェック
    # ------------------------------------------------------------------ #

    def _check_position_size(self, amount: float, balance: float) -> tuple[bool, str]:
        if balance <= 0:
            return False, "残高が0以下"
        ratio = amount / balance
        if ratio > self.MAX_SINGLE_POSITION:
            return False, (
                f"ポジションサイズオーバー: {ratio:.1%} > 上限{self.MAX_SINGLE_POSITION:.0%}"
            )
        return True, "OK"

    def _check_daily_loss(self) -> tuple[bool, str]:
        pct = self._state["today_pnl_pct"]
        if pct <= self.MAX_DAILY_LOSS:
            return False, (
                f"本日の最大損失到達: {pct:.2%} ≤ 上限{self.MAX_DAILY_LOSS:.0%}"
            )
        return True, "OK"

    def _check_cooldown(self) -> tuple[bool, str]:
        remaining = self._cooldown_remaining()
        if remaining:
            return False, f"連敗による自動停止中（残り {remaining}）"
        return True, "OK"

    def _cooldown_remaining(self) -> str:
        until_str = self._state.get("cooldown_until")
        if not until_str:
            return ""
        until = datetime.fromisoformat(until_str)
        remaining = until - datetime.now()
        if remaining.total_seconds() <= 0:
            self._state["cooldown_until"] = None
            self._state["consecutive_losses"] = 0
            self._save_state()
            return ""
        h, rem = divmod(int(remaining.total_seconds()), 3600)
        m = rem // 60
        return f"{h}時間{m}分"

    # ------------------------------------------------------------------ #
    # 状態管理
    # ------------------------------------------------------------------ #

    def _default_state(self) -> dict:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "last_reset": datetime.now().isoformat(),
            "today_pnl": 0.0,
            "today_pnl_pct": 0.0,
            "consecutive_losses": 0,
            "consecutive_wins": 0,
            "cooldown_until": None,
            "trades_today": [],
        }

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self._default_state()

    def _save_state(self) -> None:
        STATE_FILE.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _maybe_reset_daily(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._state.get("date") != today:
            prev = self._state.copy()
            self._state = self._default_state()
            # 連敗カウントと冷却状態は日をまたいでも引き継ぐ
            self._state["consecutive_losses"] = prev.get("consecutive_losses", 0)
            self._state["cooldown_until"] = prev.get("cooldown_until")
            self._save_state()
