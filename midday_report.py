"""
12:00 昼レポート（前場まとめ・午後戦略）

朝の予測と前場の動きを比較し、午後のアクションを提案。
使用API: yfinance（無料）+ DuckDuckGo（無料）+ Groq（無料）
Tavily/Exa は使わない（コスト節約）

使い方:
  python midday_report.py          # 通常実行
"""
import os
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

WATCHLIST = [
    {"code": "7203", "name": "トヨタ自動車"},
    {"code": "6758", "name": "ソニーグループ"},
    {"code": "9984", "name": "ソフトバンクグループ"},
    {"code": "4063", "name": "信越化学工業"},
    {"code": "8035", "name": "東京エレクトロン"},
    {"code": "6857", "name": "アドバンテスト"},
]


def build_midday_report() -> str:
    from market_data import format_macro_snapshot, format_stocks_snapshot, format_news_ddg
    from prediction_log import get_today_predictions

    today = datetime.date.today().strftime("%Y/%m/%d")
    now = datetime.datetime.now().strftime("%H:%M")
    lines = [f"🍱 昼レポート【{today} {now}】前場まとめ・午後戦略", ""]

    # ── マクロ現況 ───────────────────────────────────────────
    lines.append(format_macro_snapshot())
    lines.append("")

    # ── 銘柄現在値＆朝予測との比較 ───────────────────────────
    codes = [s["code"] for s in WATCHLIST]
    lines.append(format_stocks_snapshot(codes))
    lines.append("")

    # 朝の予測と比較
    morning_preds = get_today_predictions()
    if morning_preds:
        lines.append("📊 朝予測 vs 前場実績")
        from market_data import get_current_price
        for p in morning_preds:
            current = get_current_price(p["code"])
            if not current:
                continue
            pred_price = p.get("price", current)
            change = current - pred_price
            change_pct = change / pred_price * 100 if pred_price else 0
            pred_5d = p.get("pred_5d", 0)
            score = p.get("signal_score", 0)

            # 朝のシグナルスコアと実際の方向が一致しているか
            direction_match = (change >= 0) == (p.get("trend_slope", 0) >= 0)
            icon = "OK" if direction_match else "NG"
            lines.append(
                f"  [{icon}] {p['name']}({p['code']}): "
                f"朝{pred_price:,.0f}->今{current:,.0f}円 ({change_pct:+.1f}%)  "
                f"スコア{score:+d}"
            )
        lines.append("")

    # ── DDGニュース（前場中の動き）───────────────────────────
    ddg_news = format_news_ddg([
        "Japan stock market morning session today",
        "Nikkei 225 midday update",
    ], max_each=2)
    lines.append("📰 前場ニュース")
    lines.append(ddg_news)
    lines.append("")

    # ── Groq午後戦略 ─────────────────────────────────────────
    try:
        from llm_client import chat
        from market_data import get_macro_snapshot, get_current_price

        snap = get_macro_snapshot()
        macro_str = ", ".join(f"{k}:{v:.1f}" for k, v in list(snap.items())[:4])

        stocks_str = ""
        for p in morning_preds[:4]:
            price = get_current_price(p["code"])
            if price:
                pred = p.get("price", price)
                chg = (price - pred) / pred * 100 if pred else 0
                stocks_str += f"{p['name']}: {chg:+.1f}% "

        prompt = (
            f"日本株 昼休み分析（{today}）\n"
            f"マクロ: {macro_str}\n"
            f"前場騰落: {stocks_str}\n\n"
            f"以下を50字以内で各1行:\n"
            f"前場総評: \n"
            f"午後の注目点: \n"
            f"推奨アクション: "
        )
        analysis = chat(prompt, provider="groq")
        if analysis:
            lines.append("🤖 午後戦略（AI）")
            lines.append(analysis)
            lines.append("")
    except Exception as e:
        lines.append(f"[AI分析スキップ: {e}]")
        lines.append("")

    lines.append("⏰ 後場 12:30〜15:30 | 終了レポートは15:30に届きます")
    return "\n".join(lines)


def send_discord(message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or "xxxx" in url:
        print("[Discord未設定]\n", message)
        return
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        requests.post(url, json={"content": chunk}, timeout=10)


def main() -> None:
    print("昼レポート生成中...")
    report = build_midday_report()
    print(report)
    print("\nDiscord送信中...")
    send_discord(report)
    print("完了。")


if __name__ == "__main__":
    main()
