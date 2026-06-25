"""
15:30 市場終了後レポート
- 保有ポジションのSLチェック
- 本日損益サマリー
- 翌日の準備メモ生成
- Discord送信

使い方:
  python close_report.py                    # 通常実行
  python close_report.py add 7203 3400 100  # ポジション追加（コード 取得単価 株数）
  python close_report.py remove 7203        # ポジション削除（決済済み）
  python close_report.py list               # 保有一覧
"""
import os
import sys
import json
import datetime
import requests
from pathlib import Path
from dotenv import load_dotenv
from risk_manager import RiskManager
from technical import technical_scan

load_dotenv()

HOLDINGS_FILE = Path(__file__).parent / "holdings.json"
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000000"))

STOCK_NAMES = {
    "7203": "トヨタ自動車",
    "6758": "ソニーグループ",
    "9984": "ソフトバンクグループ",
    "4063": "信越化学工業",
    "8035": "東京エレクトロン",
    "6857": "アドバンテスト",
}


# ------------------------------------------------------------------ #
# holdings.json 操作
# ------------------------------------------------------------------ #

def load_holdings() -> list:
    if HOLDINGS_FILE.exists():
        return json.loads(HOLDINGS_FILE.read_text(encoding="utf-8")).get("positions", [])
    return []


def save_holdings(positions: list) -> None:
    HOLDINGS_FILE.write_text(
        json.dumps({"positions": positions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cmd_add(code: str, entry_price: float, shares: int) -> None:
    positions = load_holdings()
    # 既存ポジションがあれば上書き
    positions = [p for p in positions if p["code"] != code]
    positions.append({
        "code": code,
        "name": STOCK_NAMES.get(code, code),
        "entry_price": entry_price,
        "shares": shares,
        "entry_date": datetime.date.today().isoformat(),
    })
    save_holdings(positions)
    cost = entry_price * shares
    print(f"✅ 追加: {STOCK_NAMES.get(code, code)}({code})  "
          f"{entry_price:,.0f}円×{shares}株 = {cost:,.0f}円")


def cmd_remove(code: str) -> None:
    positions = load_holdings()
    before = len(positions)
    positions = [p for p in positions if p["code"] != code]
    save_holdings(positions)
    if len(positions) < before:
        print(f"✅ 削除: {STOCK_NAMES.get(code, code)}({code})")
    else:
        print(f"⚠️  {code} は保有リストにありません")


def cmd_list() -> None:
    positions = load_holdings()
    if not positions:
        print("保有ポジションなし")
        return
    print("【保有ポジション一覧】")
    for p in positions:
        cost = p["entry_price"] * p["shares"]
        print(f"  {p['name']}({p['code']})  "
              f"取得: {p['entry_price']:,.0f}円 × {p['shares']}株 = {cost:,.0f}円  "
              f"({p['entry_date']})")


# ------------------------------------------------------------------ #
# 終了レポート生成
# ------------------------------------------------------------------ #

def _fetch_current_price(code: str) -> float | None:
    """現在値を取得（yfinance優先、J-Quantsフォールバック）"""
    # yfinance（無料・リアルタイム）
    try:
        from market_data import get_current_price
        price = get_current_price(code)
        if price:
            return price
    except Exception:
        pass

    # J-Quants（フォールバック）
    try:
        from technical import _get_headers, _fetch_ohlcv
        headers = _get_headers()
        if not headers:
            return None
        quotes = _fetch_ohlcv(code, headers, days=80)
        if quotes:
            return float(quotes[-1]["C"])
    except Exception:
        pass
    return None


def build_close_report(rm: RiskManager) -> str:
    today = datetime.date.today().strftime("%Y/%m/%d")
    now = datetime.datetime.now().strftime("%H:%M")
    lines = [f"📊 終了レポート【{today} {now}】", ""]

    # ── 本日損益サマリー ──────────────────────────────────────
    lines.append(rm.status_report())
    lines.append("")

    # ── 保有ポジションSLチェック ──────────────────────────────
    positions = load_holdings()
    if not positions:
        lines.append("📂 保有ポジション: なし")
    else:
        lines.append("📂 保有ポジション SLチェック")
        for p in positions:
            current = _fetch_current_price(p["code"])
            if current is None:
                lines.append(f"  ⚪ {p['name']}({p['code']}): 現在値取得不可")
                continue

            sl_hit, sl_msg = rm.check_stop_loss(p["code"], p["entry_price"], current)
            pnl_pct = (current - p["entry_price"]) / p["entry_price"]
            pnl_yen = pnl_pct * p["entry_price"] * p["shares"]
            icon = "🚨" if sl_hit else ("📈" if pnl_pct >= 0 else "📉")

            lines.append(
                f"  {icon} {p['name']}({p['code']}): "
                f"{p['entry_price']:,.0f}→{current:,.0f}円  "
                f"{pnl_pct:+.2%} ({pnl_yen:+,.0f}円)  {sl_msg}"
            )
            if sl_hit:
                lines.append(f"     ⚠️ ストップロス推奨！手動で決済を検討してください")

    lines.append("")

    # ── 保有銘柄の未来予測 ───────────────────────────────────
    if positions:
        lines.append("🔮 保有銘柄 予測")
        try:
            from forecast import forecast_stock
            for p in positions:
                fc = forecast_stock(p["code"], p["name"])
                lines.append(fc)
                lines.append("")
        except Exception as e:
            lines.append(f"  予測エラー: {e}")
        lines.append("")

    # ── 保有銘柄の出口戦略（Prompt #3スタイル）──────────────
    if positions:
        lines.append("📤 出口戦略（保有銘柄）")
        for p in positions:
            current = _fetch_current_price(p["code"])
            if not current:
                continue
            cost    = p["entry_price"]
            shares  = p["shares"]
            pnl_pct = (current - cost) / cost
            pnl_yen = (current - cost) * shares

            # 3つの出口戦略をルールベースで生成
            # 保守的: 現在値付近で一部利食い or SL遵守
            # バランス: 半分利食い + 残りはトレーリング
            # 積極的: 目標値まで全保有
            if pnl_pct >= 0.05:
                # 含み益あり
                partial_sell = current * 0.995
                trail_sl     = cost + (current - cost) * 0.5  # 利益の半分を守るSL
                target       = current * 1.05

                lines.append(f"\n  {p['name']}({p['code']})  "
                             f"取得{cost:,.0f}円 → 現在{current:,.0f}円  "
                             f"含み益 {pnl_pct:+.1%} ({pnl_yen:+,.0f}円)")
                lines.append(f"    保守的: 今すぐ全売り → 利益確定 ({pnl_yen:+,.0f}円)")
                lines.append(f"    バランス: 半分売り({partial_sell:,.0f}円)、残りSL={trail_sl:,.0f}円に引き上げ")
                lines.append(f"    積極的:  目標{target:,.0f}円(+{(target-cost)/cost:.0%})まで全保有")

            elif pnl_pct <= -0.05:
                # 含み損あり
                sl_line  = cost * 0.95  # -5%ライン
                avg_down = cost * 0.97  # ナンピン候補
                target   = cost * 1.02

                lines.append(f"\n  {p['name']}({p['code']})  "
                             f"取得{cost:,.0f}円 → 現在{current:,.0f}円  "
                             f"含み損 {pnl_pct:+.1%} ({pnl_yen:+,.0f}円)")
                lines.append(f"    保守的: 今すぐ損切り → 損失確定 ({pnl_yen:+,.0f}円) ※規律優先")
                lines.append(f"    バランス: {sl_line:,.0f}円({-0.05:.0%})をSLに設定して様子見")
                lines.append(f"    積極的:  {avg_down:,.0f}円付近で追加購入(ナンピン)して平均コスト下げ")

            else:
                lines.append(f"\n  {p['name']}({p['code']})  "
                             f"取得{cost:,.0f}円 → 現在{current:,.0f}円  "
                             f"ほぼ横ばい ({pnl_pct:+.1%})")
                lines.append(f"    → 損切りライン: {cost*0.95:,.0f}円(-5%)  目標: {cost*1.07:,.0f}円(+7%)")
        lines.append("")

    # ── 翌日の準備 ───────────────────────────────────────────
    next_ok, next_reason = rm.check_before_order("_", ACCOUNT_BALANCE * 0.15, ACCOUNT_BALANCE)
    lines.append("🗓 明日の取引可否")
    lines.append(f"  {'✅ 取引可能' if next_ok else '🚫 ' + next_reason}")
    lines.append(f"  連敗: {rm.consecutive_losses}回 / 上限{RiskManager.MAX_CONSECUTIVE_LOSS}回")
    lines.append("")
    lines.append("💡 明朝7:00に自動レポートが届きます")

    return "\n".join(lines)


def send_discord(message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or "xxxx" in url:
        print(f"[Discord未設定 / URL={url!r}]")
        print(message)
        return
    print(f"[Discord送信先] URL末尾: ...{url[-20:]}")
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for i, chunk in enumerate(chunks):
        resp = requests.post(url, json={"content": chunk}, timeout=10)
        print(f"  チャンク{i+1}: HTTP {resp.status_code}")
        if not resp.ok:
            print(f"  エラー詳細: {resp.text[:200]}")


# ------------------------------------------------------------------ #
# エントリーポイント
# ------------------------------------------------------------------ #

def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "add":
        if len(args) < 4:
            print("使い方: python close_report.py add <コード> <取得単価> <株数>")
            sys.exit(1)
        cmd_add(args[1], float(args[2]), int(args[3]))
        return

    if args and args[0] == "remove":
        if len(args) < 2:
            print("使い方: python close_report.py remove <コード>")
            sys.exit(1)
        cmd_remove(args[1])
        return

    if args and args[0] == "list":
        cmd_list()
        return

    # 前場終了モード（11:30）: 軽量版・予測分析なし
    if args and args[0] == "morning-close":
        rm = RiskManager()
        now = datetime.datetime.now().strftime("%H:%M")
        today = datetime.date.today().strftime("%Y/%m/%d")
        lines = [f"📊 前場終了レポート【{today} {now}】", ""]
        try:
            from market_data import format_macro_snapshot, format_stocks_snapshot
            lines.append(format_macro_snapshot())
            lines.append("")
            lines.append(format_stocks_snapshot(
                [s["code"] for s in [
                    {"code": "7203"}, {"code": "6758"}, {"code": "9984"},
                    {"code": "4063"}, {"code": "8035"}, {"code": "6857"},
                ]]
            ))
            lines.append("")
        except Exception as e:
            lines.append(f"[市場データ取得エラー: {e}]")
        # SLチェックのみ（分析なし）
        positions = load_holdings()
        if positions:
            lines.append("📂 保有ポジション SLチェック（前場終値）")
            for p in positions:
                current = _fetch_current_price(p["code"])
                if current is None:
                    lines.append(f"  - {p['name']}({p['code']}): 取得不可")
                    continue
                sl_hit, sl_msg = rm.check_stop_loss(p["code"], p["entry_price"], current)
                pnl_pct = (current - p["entry_price"]) / p["entry_price"]
                icon = "SL!" if sl_hit else ("+" if pnl_pct >= 0 else "-")
                lines.append(f"  [{icon}] {p['name']}: {p['entry_price']:,.0f}->{current:,.0f}円 "
                             f"{pnl_pct:+.2%}  {sl_msg}")
                if sl_hit:
                    lines.append(f"     ⚠️ ストップロス推奨！午後の判断を検討")
        lines.append("")
        lines.append("⏰ 昼レポートは12:00 | 後場終了レポートは15:30に届きます")
        report = "\n".join(lines)
        print(report)
        print("\nDiscord送信中...")
        send_discord(report)
        print("完了。")
        return

    # 通常実行（15:30）: 終了レポート生成＆Discord送信
    rm = RiskManager()
    report = build_close_report(rm)
    print(report)

    # 予測精度分析（朝の予測と実績を比較）
    print("\n予測精度分析中...")
    try:
        from prediction_analyzer import run_analysis
        analysis = run_analysis()
        full_report = report + "\n\n" + "─" * 30 + "\n" + analysis
    except Exception as e:
        full_report = report
        print(f"  分析エラー: {e}")

    print("\nDiscord送信中...")
    send_discord(full_report)
    print("完了。")


if __name__ == "__main__":
    main()
