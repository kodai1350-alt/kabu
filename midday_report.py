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
from watchlist import load_watchlist

load_dotenv()

WATCHLIST = load_watchlist()


def build_midday_report() -> str:
    from market_data import format_macro_snapshot, format_stocks_snapshot, format_news_ddg
    from prediction_log import get_today_predictions

    JST = datetime.timezone(datetime.timedelta(hours=9))
    now_jst = datetime.datetime.now(JST)
    today = now_jst.strftime("%Y/%m/%d")
    now = now_jst.strftime("%H:%M")
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
        lines.append("📊 朝の予測 vs 前場の実際の動き")
        from market_data import get_current_price
        hit = 0
        total_p = 0
        rows = []
        for p in morning_preds:
            current = get_current_price(p["code"])
            if not current:
                continue
            total_p += 1
            pred_price = p.get("price", current)
            change_pct = (current - pred_price) / pred_price * 100 if pred_price else 0
            score = p.get("signal_score", 0)
            slope = p.get("trend_slope", 0)

            # 朝の予測方向（スコア/傾き）と実際の方向が一致しているか
            pred_up = (score > 0) or (score == 0 and slope > 0)
            actual_up = change_pct > 0.05
            actual_down = change_pct < -0.05
            if actual_up == pred_up or (not actual_up and not actual_down):
                match = True
                hit += 1
            else:
                match = False

            pred_dir = "上昇予測" if pred_up else "下落予測"
            actual_dir = "上昇" if actual_up else ("下落" if actual_down else "横ばい")
            result_icon = "的中" if match else "外れ"
            rows.append(
                f"  {'✅' if match else '❌'} {p['name']}({p['code']}):  "
                f"朝={pred_dir} → 実際={actual_dir}({change_pct:+.1f}%)  [{result_icon}]"
            )
        lines.extend(rows)
        if total_p > 0:
            lines.append(f"  → 的中率: {hit}/{total_p}銘柄 ({hit/total_p*100:.0f}%)")
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


def main() -> None:
    print("昼レポート生成中...")
    report = build_midday_report()
    print(report)
    print("\nDiscord送信中...")
    send_discord(report)
    print("完了。")


if __name__ == "__main__":
    main()
