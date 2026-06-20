"""
取引結果を手動記録するCLIスクリプト
使い方:
  python record_trade.py 7203 3400 3250   # 銘柄コード 取得単価 決済単価
  python record_trade.py 7203 -0.044      # 銘柄コード 損益率（-4.4%）
  python record_trade.py --status          # 現在のリスク状態を表示
"""
import sys
import os
import argparse
from dotenv import load_dotenv
from risk_manager import RiskManager

load_dotenv()

ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000000"))


def cmd_status(rm: RiskManager) -> None:
    print(rm.status_report())


def cmd_record(rm: RiskManager, ticker: str, pnl_pct: float) -> None:
    print(f"\n【記録前】")
    print(rm.status_report())

    rm.record_trade_result(ticker, pnl_pct, ACCOUNT_BALANCE)

    pnl_yen = ACCOUNT_BALANCE * pnl_pct
    sign = "+" if pnl_pct >= 0 else ""
    print(f"\n✅ 記録完了: {ticker}  {sign}{pnl_pct:.2%}  ({sign}{pnl_yen:,.0f}円)")
    print(f"\n【記録後】")
    print(rm.status_report())

    ok, reason = rm.check_before_order(ticker, ACCOUNT_BALANCE * 0.15, ACCOUNT_BALANCE)
    print(f"\n次回注文可否: {'✅ OK' if ok else '🚫 ' + reason}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="取引結果をRiskManagerに記録する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python record_trade.py --status
  python record_trade.py 7203 3400 3250       # 取得単価→決済単価で自動計算
  python record_trade.py 7203 -0.044          # 損益率を直接指定（-4.4%）
  python record_trade.py 7203 0.032           # 利益 +3.2%
        """,
    )
    parser.add_argument("--status", action="store_true", help="現在のリスク状態を表示")
    parser.add_argument("ticker", nargs="?", help="銘柄コード（例: 7203）")
    parser.add_argument("arg2", nargs="?", type=float, help="取得単価 または 損益率")
    parser.add_argument("arg3", nargs="?", type=float, help="決済単価（取得単価指定時のみ）")

    args = parser.parse_args()
    rm = RiskManager()

    if args.status or not args.ticker:
        cmd_status(rm)
        return

    if args.arg2 is None:
        parser.error("損益率または取得単価を指定してください")

    if args.arg3 is not None:
        # 取得単価 → 決済単価 → 損益率を計算
        entry, exit_ = args.arg2, args.arg3
        if entry <= 0:
            parser.error("取得単価は0より大きい値を指定してください")
        pnl_pct = (exit_ - entry) / entry
    else:
        # 損益率を直接指定（-0.05 = -5%）
        pnl_pct = args.arg2
        if abs(pnl_pct) > 1:
            parser.error("損益率は-1〜1の範囲で指定してください（例: -0.05 = -5%）")

    cmd_record(rm, args.ticker, pnl_pct)


if __name__ == "__main__":
    main()
