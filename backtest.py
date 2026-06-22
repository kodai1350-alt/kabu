"""
バックテストモジュール（Vibe-Trading連携）

使い方:
  python backtest.py                        # デフォルト: WATCHLIST全銘柄 移動平均クロス
  python backtest.py 7203                   # 個別銘柄
  python backtest.py 7203 --strategy rsi    # 戦略指定 (ma_cross / rsi / bb)
  python backtest.py 7203 --days 180        # データ期間指定

Vibe-Tradingがインストールされていない場合は簡易バックテストにフォールバック。
"""
import os
import sys
import argparse
import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

WATCHLIST = ["7203", "6758", "9984", "4063", "8035", "6857"]

STOCK_NAMES = {
    "7203": "トヨタ自動車",
    "6758": "ソニーグループ",
    "9984": "ソフトバンクグループ",
    "4063": "信越化学工業",
    "8035": "東京エレクトロン",
    "6857": "アドバンテスト",
}


# ------------------------------------------------------------------ #
# 簡易バックテストエンジン（Vibe-Tradingフォールバック）
# ------------------------------------------------------------------ #

def _simple_ma_cross(closes: list[float], short: int = 20, long_: int = 50) -> dict:
    """移動平均クロス戦略の簡易バックテスト"""
    if len(closes) < long_ + 1:
        return {"error": f"データ不足 ({len(closes)}件 < {long_ + 1}件必要)"}

    capital = 1_000_000.0
    position = 0
    entry_price = 0.0
    trades: list[dict] = []

    for i in range(long_, len(closes)):
        short_ma = sum(closes[i - short:i]) / short
        long_ma = sum(closes[i - long_:i]) / long_

        prev_short = sum(closes[i - short - 1:i - 1]) / short
        prev_long = sum(closes[i - long_ - 1:i - 1]) / long_

        price = closes[i]

        # ゴールデンクロス → 買い
        if prev_short <= prev_long and short_ma > long_ma and position == 0:
            shares = int(capital / price)
            if shares > 0:
                position = shares
                entry_price = price
                trades.append({"type": "buy", "price": price, "shares": shares, "idx": i})

        # デッドクロス → 売り
        elif prev_short >= prev_long and short_ma < long_ma and position > 0:
            pnl = (price - entry_price) * position
            capital += pnl
            trades.append({"type": "sell", "price": price, "shares": position,
                           "idx": i, "pnl": pnl, "pnl_pct": (price - entry_price) / entry_price})
            position = 0

    # 未決済ポジションを時価評価
    if position > 0:
        price = closes[-1]
        pnl = (price - entry_price) * position
        capital += pnl
        trades.append({"type": "sell(open)", "price": price, "shares": position,
                       "idx": len(closes) - 1, "pnl": pnl,
                       "pnl_pct": (price - entry_price) / entry_price})

    wins = [t for t in trades if t.get("type", "").startswith("sell") and t.get("pnl", 0) > 0]
    sells = [t for t in trades if t.get("type", "").startswith("sell")]
    total_return = (capital - 1_000_000) / 1_000_000

    return {
        "strategy": f"移動平均クロス (MA{short}/MA{long_})",
        "trades": len(sells),
        "win_rate": len(wins) / len(sells) if sells else 0,
        "total_return": total_return,
        "final_capital": capital,
        "pnl_list": [t.get("pnl_pct", 0) for t in sells],
    }


def _simple_rsi(closes: list[float], period: int = 14,
                oversold: float = 30, overbought: float = 70) -> dict:
    """RSI平均回帰戦略の簡易バックテスト"""
    if len(closes) < period + 1:
        return {"error": f"データ不足"}

    capital = 1_000_000.0
    position = 0
    entry_price = 0.0
    trades: list[dict] = []

    def calc_rsi(prices, p):
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas[-p:]]
        losses = [abs(min(d, 0)) for d in deltas[-p:]]
        avg_gain = sum(gains) / p
        avg_loss = sum(losses) / p
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    for i in range(period + 1, len(closes)):
        rsi = calc_rsi(closes[:i], period)
        price = closes[i]

        if rsi < oversold and position == 0:
            shares = int(capital / price)
            if shares > 0:
                position = shares
                entry_price = price
                trades.append({"type": "buy", "price": price, "shares": shares})

        elif rsi > overbought and position > 0:
            pnl = (price - entry_price) * position
            capital += pnl
            trades.append({"type": "sell", "price": price, "shares": position,
                           "pnl": pnl, "pnl_pct": (price - entry_price) / entry_price})
            position = 0

    if position > 0:
        price = closes[-1]
        pnl = (price - entry_price) * position
        capital += pnl
        trades.append({"type": "sell(open)", "price": price, "shares": position,
                       "pnl": pnl, "pnl_pct": (price - entry_price) / entry_price})

    wins = [t for t in trades if t.get("type", "").startswith("sell") and t.get("pnl", 0) > 0]
    sells = [t for t in trades if t.get("type", "").startswith("sell")]
    total_return = (capital - 1_000_000) / 1_000_000

    return {
        "strategy": f"RSI({period}) 過売{oversold}/過買{overbought}",
        "trades": len(sells),
        "win_rate": len(wins) / len(sells) if sells else 0,
        "total_return": total_return,
        "final_capital": capital,
        "pnl_list": [t.get("pnl_pct", 0) for t in sells],
    }


def _simple_bb(closes: list[float], period: int = 20, sigma: float = 2.0) -> dict:
    """ボリンジャーバンド逆張り戦略の簡易バックテスト"""
    if len(closes) < period + 1:
        return {"error": "データ不足"}

    import math

    capital = 1_000_000.0
    position = 0
    entry_price = 0.0
    trades: list[dict] = []

    for i in range(period, len(closes)):
        window = closes[i - period:i]
        ma = sum(window) / period
        std = math.sqrt(sum((x - ma) ** 2 for x in window) / period)
        lower = ma - sigma * std
        upper = ma + sigma * std
        price = closes[i]

        if price < lower and position == 0:
            shares = int(capital / price)
            if shares > 0:
                position = shares
                entry_price = price
                trades.append({"type": "buy", "price": price})

        elif price > ma and position > 0:
            pnl = (price - entry_price) * position
            capital += pnl
            trades.append({"type": "sell", "price": price, "pnl": pnl,
                           "pnl_pct": (price - entry_price) / entry_price})
            position = 0

    if position > 0:
        price = closes[-1]
        pnl = (price - entry_price) * position
        capital += pnl
        trades.append({"type": "sell(open)", "price": price, "pnl": pnl,
                       "pnl_pct": (price - entry_price) / entry_price})

    wins = [t for t in trades if t.get("type", "").startswith("sell") and t.get("pnl", 0) > 0]
    sells = [t for t in trades if t.get("type", "").startswith("sell")]
    total_return = (capital - 1_000_000) / 1_000_000

    return {
        "strategy": f"ボリンジャーバンド({period},{sigma}σ) 逆張り",
        "trades": len(sells),
        "win_rate": len(wins) / len(sells) if sells else 0,
        "total_return": total_return,
        "final_capital": capital,
        "pnl_list": [t.get("pnl_pct", 0) for t in sells],
    }


# ------------------------------------------------------------------ #
# Vibe-Trading APIバックテスト（利用可能時）
# ------------------------------------------------------------------ #

def _vibe_backtest(code: str, strategy: str, closes: list[float]) -> Optional[dict]:
    """Vibe-Tradingライブラリでバックテスト（インストール済みの場合）"""
    try:
        import vibetrading.backtest as vbt
        import vibetrading.tools as vbt_tools

        if strategy == "ma_cross":
            strategy_code = """
from vibetrading import vibe, get_price, long, short as short_pos, close_long

@vibe
def strategy(bar):
    closes = [get_price(i) for i in range(-50, 0)]
    if len(closes) < 51:
        return
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50
    prev_ma20 = sum(closes[-21:-1]) / 20
    prev_ma50 = sum(closes[-51:-1]) / 50
    price = get_price(0)
    if prev_ma20 <= prev_ma50 and ma20 > ma50:
        long(size=0.95)
    elif prev_ma20 >= prev_ma50 and ma20 < ma50:
        close_long()
"""
        else:
            return None

        data = {"close": closes}
        results = vbt.run(strategy_code, data=data, interval="1d")
        m = results.get("metrics", {})
        return {
            "strategy": f"Vibe-Trading {strategy}",
            "trades": m.get("total_trades", 0),
            "win_rate": m.get("win_rate", 0),
            "total_return": m.get("total_return", 0),
            "final_capital": 1_000_000 * (1 + m.get("total_return", 0)),
            "sharpe": m.get("sharpe_ratio"),
            "max_drawdown": m.get("max_drawdown"),
        }
    except ImportError:
        return None
    except Exception:
        return None


# ------------------------------------------------------------------ #
# メイン
# ------------------------------------------------------------------ #

def _fetch_closes(code: str, days: int = 180) -> list[float]:
    """終値リストを取得（yfinance優先、J-Quantsフォールバック）"""
    # yfinance（無料・キー不要）
    try:
        from market_data import get_closes
        period = "1y" if days >= 300 else ("6mo" if days >= 150 else "3mo")
        closes = get_closes(code, period=period)
        if closes:
            return closes[-days:]
    except Exception:
        pass

    # J-Quants（フォールバック）
    try:
        from technical import _get_headers, _fetch_ohlcv
        headers = _get_headers()
        if not headers:
            return []
        quotes = _fetch_ohlcv(code, headers, days=days)
        return [float(q["C"]) for q in quotes if q.get("C") is not None]
    except Exception as e:
        print(f"  J-Quants取得エラー: {e}")
        return []


def _format_result(code: str, result: dict) -> str:
    if "error" in result:
        return f"  ❌ {result['error']}"
    lines = []
    lines.append(f"  戦略: {result['strategy']}")
    lines.append(f"  取引回数: {result['trades']}回")
    lines.append(f"  勝率: {result['win_rate']:.1%}")
    lines.append(f"  総損益: {result['total_return']:+.2%}")
    lines.append(f"  最終資本: {result['final_capital']:,.0f}円 (初期100万円)")
    if result.get("sharpe"):
        lines.append(f"  シャープ比: {result['sharpe']:.2f}")
    if result.get("max_drawdown"):
        lines.append(f"  最大DD: {result['max_drawdown']:.2%}")
    return "\n".join(lines)


def run_backtest(code: str, strategy: str = "ma_cross", days: int = 180) -> str:
    name = STOCK_NAMES.get(code, code)
    today = datetime.date.today().strftime("%Y/%m/%d")
    lines = [f"📊 バックテスト: {name}({code})  [{today}]", ""]

    closes = _fetch_closes(code, days=days)
    if not closes:
        lines.append("  ⚠️ J-Quantsデータ取得不可（無料プランは2026-03-27まで）")
        lines.append("  デモデータで実行します...")
        import math
        closes = [3000 + 200 * math.sin(i * 0.15) + i * 0.5 for i in range(days)]

    lines.append(f"  データ期間: {days}日  終値件数: {len(closes)}件")
    lines.append(f"  最新終値: {closes[-1]:,.0f}円")
    lines.append("")

    # Vibe-Trading優先、なければ簡易エンジン
    vibe_result = _vibe_backtest(code, strategy, closes)

    if strategy == "ma_cross":
        result = vibe_result or _simple_ma_cross(closes)
    elif strategy == "rsi":
        result = _simple_rsi(closes)
    elif strategy == "bb":
        result = _simple_bb(closes)
    else:
        result = _simple_ma_cross(closes)

    if vibe_result and strategy == "ma_cross":
        lines.append("【Vibe-Trading バックテスト結果】")
    else:
        lines.append("【簡易バックテスト結果】")

    lines.append(_format_result(code, result))

    # 全3戦略比較
    if strategy == "all":
        lines.append("")
        lines.append("【全戦略比較】")
        for s_name, s_func in [
            ("MA Cross", lambda c: _simple_ma_cross(c)),
            ("RSI", lambda c: _simple_rsi(c)),
            ("BB逆張り", lambda c: _simple_bb(c)),
        ]:
            r = s_func(closes)
            ret = r.get("total_return", 0)
            wr = r.get("win_rate", 0)
            lines.append(f"  {s_name:10s}  総損益: {ret:+.2%}  勝率: {wr:.0%}  取引: {r.get('trades', 0)}回")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="バックテスト実行")
    parser.add_argument("code", nargs="?", default=None, help="銘柄コード (省略時はWATCHLIST全銘柄)")
    parser.add_argument("--strategy", choices=["ma_cross", "rsi", "bb", "all"],
                        default="all", help="戦略 (デフォルト: all)")
    parser.add_argument("--days", type=int, default=180, help="バックテスト期間(日数, デフォルト:180)")
    args = parser.parse_args()

    targets = [args.code] if args.code else WATCHLIST

    for code in targets:
        result = run_backtest(code, strategy=args.strategy, days=args.days)
        print(result)
        print()


if __name__ == "__main__":
    main()
