"""
週末レポート（土日 08:00 JST）
- 株式市場は休場だがニュース・マクロは動いている
- 来週の相場に影響する情報を収集してDiscord送信
- テクニカル分析（価格不要）も実施
"""
import os
import datetime
import requests
from dotenv import load_dotenv
from watchlist import load_watchlist

load_dotenv()

JST = datetime.timezone(datetime.timedelta(hours=9))

WATCHLIST = load_watchlist()

# 来週の重要イベント検索キーワード
WEEKLY_QUERIES = [
    "Japan stock market next week outlook",
    "economic calendar Japan next week",
    "Federal Reserve FOMC next week",
    "USD JPY forecast next week",
    "Nikkei 225 weekly analysis",
    "semiconductor market news this week",
    "日本株 来週 見通し",
    "米国株 来週 イベント",
]

# 個別銘柄週末ニュース
STOCK_QUERIES = [
    "Toyota earnings outlook",
    "Sony semiconductor news",
    "SoftBank investment portfolio news",
    "Tokyo Electron TSMC orders",
    "semiconductor equipment demand",
]


def _ddg_search(query: str, max_results: int = 3) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def build_weekend_report() -> str:
    now_jst  = datetime.datetime.now(JST)
    today    = now_jst.strftime("%Y/%m/%d")
    weekday  = ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()]
    lines    = []
    sep      = "━" * 38

    lines += [
        f"📅 週末マーケット情報【{today}（{weekday}）】",
        "株式市場は休場 | 来週に向けた情報収集レポート",
        sep, "",
    ]

    # ── 1. マクロ動向（週末でも動く: 為替・先物・暗号資産）──────
    lines.append("🌍 週末マクロ動向")
    try:
        from market_data import format_macro_snapshot
        lines.append(format_macro_snapshot())
    except Exception as e:
        lines.append(f"  [取得エラー: {e}]")
    lines.append("")

    # ── 2. 今週の振り返り + 来週の見通しニュース ──────────────
    lines.append(f"{sep}")
    lines.append("📰 来週に影響するニュース")
    lines.append("")

    seen = set()
    news_count = 0
    for query in WEEKLY_QUERIES:
        results = _ddg_search(query, max_results=2)
        for r in results:
            title = r.get("title", "")
            body  = r.get("body", "")[:120]
            if title in seen:
                continue
            seen.add(title)
            lines.append(f"・{title}")
            if body:
                lines.append(f"  {body}")
            news_count += 1
            if news_count >= 8:
                break
        if news_count >= 8:
            break
    lines.append("")

    # ── 3. 個別銘柄ニュース ───────────────────────────────────
    lines.append(f"{sep}")
    lines.append("🏭 監視銘柄 週末ニュース")
    lines.append("")

    seen2 = set()
    stock_news_count = 0
    for query in STOCK_QUERIES:
        results = _ddg_search(query, max_results=2)
        for r in results:
            title = r.get("title", "")
            body  = r.get("body", "")[:100]
            if title in seen2:
                continue
            seen2.add(title)
            lines.append(f"・{title}")
            if body:
                lines.append(f"  {body}")
            stock_news_count += 1
            if stock_news_count >= 6:
                break
        if stock_news_count >= 6:
            break
    lines.append("")

    # ── 4. テクニカル分析（週末でも計算可能）────────────────────
    lines.append(f"{sep}")
    lines.append("📊 週末テクニカル分析（金曜終値ベース）")
    lines.append("")

    try:
        from market_data import get_closes, get_volume_ratio
        from forecast import calc_signal_score, calc_support_resistance

        for stock in WATCHLIST:
            try:
                closes = get_closes(stock["code"], period="3mo")
                if len(closes) < 20:
                    continue
                current = closes[-1]
                signal  = calc_signal_score(closes)
                sr      = calc_support_resistance(closes)
                score   = signal["score"]
                label   = signal["label"]
                sup     = sr.get("support", current * 0.95)
                res     = sr.get("resistance", current * 1.05)

                score_bar = "▲" * max(0, score) + "▼" * max(0, -score) if score != 0 else "→"
                lines.append(
                    f"  {stock['name']}({stock['code']}): "
                    f"{current:,.0f}円  {score_bar} {label}"
                )
                lines.append(
                    f"    支持線: {sup:,.0f}円 / 抵抗線: {res:,.0f}円"
                )
            except Exception:
                continue
    except Exception as e:
        lines.append(f"  [テクニカルエラー: {e}]")
    lines.append("")

    # ── 5. AI来週予測 ────────────────────────────────────────
    lines.append(f"{sep}")
    lines.append("🤖 AI 来週の注目ポイント")
    lines.append("")

    try:
        from llm_client import chat
        news_summary = "\n".join(lines[20:40])  # ニュース部分を抜粋

        prompt = (
            f"日本株 週末分析（{today}）\n"
            f"以下のニュースをもとに来週の日本株について分析してください:\n"
            f"{news_summary[:800]}\n\n"
            f"以下を各2〜3行で:\n"
            f"1. 来週の市場環境予測:\n"
            f"2. 注目すべきリスク要因:\n"
            f"3. 注目銘柄セクター:\n"
            f"4. 月曜日の戦略:"
        )
        analysis = chat(prompt, provider="groq")
        if analysis:
            lines.append(analysis)
        else:
            lines.append("  [AI分析スキップ]")
    except Exception as e:
        lines.append(f"  [AI分析エラー: {e}]")
    lines.append("")

    lines.append(f"{sep}")
    lines.append("⏰ 次回: 月曜 07:00 に朝レポートが届きます")

    return "\n".join(lines)


def send_discord(message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or "xxxx" in url:
        print(f"[Discord未設定 / URL={url!r}]")
        print(message)
        return
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for i, chunk in enumerate(chunks):
        resp = requests.post(url, json={"content": chunk}, timeout=10)
        print(f"  チャンク{i+1}: HTTP {resp.status_code}")
        if not resp.ok:
            print(f"  エラー詳細: {resp.text[:200]}")


def main():
    print("週末レポート生成中...")
    report = build_weekend_report()
    print(report)
    print("\nDiscord送信中...")
    send_discord(report)
    print("完了。")


if __name__ == "__main__":
    main()
