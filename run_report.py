import os
import time
import datetime
import requests
from dotenv import load_dotenv
from tavily import TavilyClient
from exa_py import Exa
from llm_client import chat
from technical import technical_scan
from edinet import scan_watchlist as edinet_scan
from risk_manager import RiskManager
from multi_agent import multi_agent_debate
from market_data import (
    format_macro_snapshot, format_stocks_snapshot,
    format_news_ddg, format_volume_scan, get_closes, get_volume_ratio,
)
from api_tracker import check_and_warn, record, get_status_report
from forecast import forecast_stock, calc_signal_score, calc_support_resistance

load_dotenv()

WATCHLIST = [
    {"code": "7203", "name": "トヨタ自動車"},
    {"code": "6758", "name": "ソニーグループ"},
    {"code": "9984", "name": "ソフトバンクグループ"},
    {"code": "4063", "name": "信越化学工業"},
    {"code": "8035", "name": "東京エレクトロン"},
    {"code": "6857", "name": "アドバンテスト"},
]

ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000000"))

MEDALS = ["🥇", "🥈", "🥉", "4.", "5.", "6."]


# ──────────────────────────────────────────────────────────────────── #
# シグナルスキャン（全銘柄を素早く評価してランク付け）
# ──────────────────────────────────────────────────────────────────── #

def _scan_all_signals() -> list[dict]:
    """全銘柄のシグナルスコア・RR比・売買判断を収集してランク付けする"""
    from forecast import _linear_regression
    results = []
    for stock in WATCHLIST:
        try:
            closes = get_closes(stock["code"], period="3mo")
            if len(closes) < 30:
                continue
            current = closes[-1]
            signal  = calc_signal_score(closes)
            sr      = calc_support_resistance(closes)
            trend   = _linear_regression(closes)
            score   = signal["score"]

            # 出来高チェック
            vol_ratio = get_volume_ratio(stock["code"])
            if vol_ratio and vol_ratio >= 2.0:
                rsi_val = signal.get("details", {}).get("rsi", (50, 0))[0]
                if rsi_val < 35:
                    score = min(5, score + 1)

            # サポート/レジスタンスを現在値近傍に限定
            support    = sr.get("support", current * 0.93)
            resistance = sr.get("resistance", current * 1.07)
            near_sup   = support    if support    >= current * 0.90 else current * 0.93
            near_res   = resistance if resistance <= current * 1.15 else current * 1.07

            # 売買判断 & プラン
            if score >= 2:
                verdict  = "今買う"
                entry    = current * 1.002
                sl       = near_sup * 0.99
                target   = near_res * 0.99
            elif score >= 0:
                verdict  = "もう少し待つ"
                entry    = current * 0.98
                sl       = near_sup * 0.98
                target   = near_res * 0.99
            else:
                verdict  = "見送り"
                entry    = current * 0.93
                sl       = current * 0.90
                target   = current * 1.03

            risk   = abs(entry - sl)
            reward = abs(target - entry)
            rr     = reward / risk if risk > 0 else 0

            # 期待値スコア（signal score × RR比）
            ev = score * rr

            results.append({
                "code":      stock["code"],
                "name":      stock["name"],
                "current":   current,
                "score":     score,
                "verdict":   verdict,
                "entry":     entry,
                "sl":        sl,
                "target":    target,
                "rr":        rr,
                "ev":        ev,
                "vol_ratio": vol_ratio,
                "label":     signal["label"],
                "slope":     trend.get("slope", 0),
            })
        except Exception:
            continue

    # 期待値（ev）の高い順に並べ替え、同点はscoreで
    results.sort(key=lambda x: (x["ev"], x["score"]), reverse=True)
    return results


def _stars(score: int) -> str:
    filled = max(0, min(5, score + 3))  # -2〜+3 → ★1〜5
    return "★" * filled + "☆" * (5 - filled)


def _build_top_picks(signals: list, trading_ok: bool) -> str:
    """おすすめ銘柄セクションを生成"""
    sep = "━" * 38
    lines = [sep, "🏆 今日のおすすめアクション", sep, ""]

    if not trading_ok:
        lines.append("⛔ 本日は取引停止中（以下は参考情報のみ）")
        lines.append("")

    buy_stocks = [s for s in signals if s["verdict"] in ("今買う", "もう少し待つ")]
    skip_stocks = [s for s in signals if s["verdict"] == "見送り"]

    for i, s in enumerate(buy_stocks):
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        entry_pct  = (s["entry"]  - s["current"]) / s["current"] * 100
        sl_pct     = (s["sl"]     - s["current"]) / s["current"] * 100
        target_pct = (s["target"] - s["current"]) / s["current"] * 100
        stars      = _stars(s["score"])
        rr_str     = f"{s['rr']:.1f}"
        vol_badge  = f"  ⚡出来高{s['vol_ratio']:.1f}倍" if s["vol_ratio"] and s["vol_ratio"] >= 1.5 else ""

        lines.append(f"{medal} {s['name']}({s['code']})  →  【{s['verdict']}】")
        lines.append(f"   現在 {s['current']:,.0f}円")
        lines.append(
            f"   エントリー {s['entry']:,.0f}円({entry_pct:+.1f}%) /"
            f" 目標 {s['target']:,.0f}円({target_pct:+.1f}%) /"
            f" 損切 {s['sl']:,.0f}円({sl_pct:+.1f}%)"
        )
        lines.append(f"   期待値 {stars}  RR比 1:{rr_str}  {s['label']}{vol_badge}")
        # 根拠1行
        slope_str = f"トレンド{s['slope']:+.0f}円/日" if abs(s["slope"]) > 0.5 else "横ばいトレンド"
        lines.append(f"   根拠: {slope_str} / {s['label']}")
        lines.append("")

    if skip_stocks:
        names = "、".join(f"{s['name']}({s['code']})" for s in skip_stocks)
        lines.append(f"⛔ 見送り: {names}")
        lines.append("   理由: シグナル弱 / 下降トレンドにつき様子見")
        lines.append("")

    lines.append(sep)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────── #
# API スキャン
# ──────────────────────────────────────────────────────────────────── #

def macro_scan(tavily: TavilyClient) -> str:
    queries = [
        "Japan stock market outlook today",
        "Federal Reserve rate USD JPY",
        "Nikkei 225 forecast",
    ]
    results = []
    for q in queries:
        r = tavily.search(q, max_results=2)
        for item in r.get("results", []):
            results.append(f"- {item['title']}: {item['content'][:200]}")
    return "\n".join(results)


def company_scan(exa: Exa, stock: dict) -> str:
    r = exa.search_and_contents(
        f"{stock['name']} 株価 ニュース",
        num_results=2,
        text={"max_characters": 300},
    )
    snippets = [f"- {res.title}: {res.text[:200]}" for res in r.results]
    return "\n".join(snippets)


def send_discord(message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or "xxxx" in url:
        print("[Discord未設定]\n", message)
        return
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        requests.post(url, json={"content": chunk}, timeout=10)


# ──────────────────────────────────────────────────────────────────── #
# メイン
# ──────────────────────────────────────────────────────────────────── #

def main():
    today      = datetime.date.today().strftime("%Y/%m/%d")
    weekday    = ["月", "火", "水", "木", "金", "土", "日"][datetime.date.today().weekday()]
    discord_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    tavily     = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    exa        = Exa(api_key=os.getenv("EXA_API_KEY"))

    rm         = RiskManager()
    trading_ok = rm.check_before_order("_", ACCOUNT_BALANCE * 0.1, ACCOUNT_BALANCE)[0]

    # ── Step 1: 全銘柄シグナルスキャン（おすすめ生成用）────────────
    print("Step 1: 銘柄シグナルスキャン中...")
    signals = _scan_all_signals()
    top_picks = _build_top_picks(signals, trading_ok)

    # ── Step 2: マーケットデータ収集 ────────────────────────────────
    print("Step 2: マーケットデータ収集中...")
    market_snapshot = format_macro_snapshot()
    stocks_snapshot = format_stocks_snapshot([s["code"] for s in WATCHLIST])
    volume_scan     = format_volume_scan([s["code"] for s in WATCHLIST])
    ddg_news        = format_news_ddg([
        "Japan stock market today",
        "Nikkei 225 today",
        "USD JPY exchange rate",
    ], max_each=2)

    # ── Step 3: 詳細データ（API残量チェック付き）────────────────────
    print("Step 3: 詳細データ収集中...")

    macro_data = ""
    if check_and_warn("tavily", discord_url):
        macro_data = macro_scan(tavily)
        record("tavily", 3)
    else:
        macro_data = ddg_news

    company_data = ""
    if check_and_warn("exa", discord_url):
        for stock in WATCHLIST:
            news = company_scan(exa, stock)
            company_data += f"\n{stock['name']}: {news[:300]}\n"
        record("exa", len(WATCHLIST))

    edinet_data   = edinet_scan(WATCHLIST)

    # テクニカル（sleepを短縮: 5→1秒）
    technical_data = ""
    for stock in WATCHLIST:
        result = technical_scan(stock["code"])
        technical_data += f"\n{result}\n"
        time.sleep(1)

    # 詳細予測
    print("Step 4: 詳細予測生成中...")
    forecast_data = ""
    for stock in WATCHLIST:
        fc = forecast_stock(stock["code"], stock["name"])
        forecast_data += f"\n{fc}\n"

    # マルチエージェント議論（上位1銘柄のみ、API節約）
    debate_data = ""
    if signals and check_and_warn("groq", discord_url):
        top = signals[0]
        ctx = f"マクロ: {macro_data[:300]}\nニュース: {company_data[:300]}"
        debate_data = multi_agent_debate(top["code"], top["name"], ctx)
        record("groq", 3)

    # ── Step 5: レポート組み立て ─────────────────────────────────────
    print("Step 5: レポート組み立て中...")
    sep = "─" * 38

    # ヘッダー
    status_icon = "✅ 取引可能" if trading_ok else "⛔ 取引停止中"
    header = f"📊 AI予測取引レポート【{today}（{weekday}）】  {status_icon}"

    # ニュース（3行に絞る）
    news_lines = [l for l in ddg_news.splitlines() if l.startswith("-")][:3]
    news_block = "📰 注目ニュース\n" + "\n".join(news_lines)

    # 詳細予測（短縮版）
    detail_block = f"🔮 詳細予測\n{forecast_data[:2000]}"

    # マルチエージェント（あれば）
    debate_block = ""
    if debate_data:
        top_name = signals[0]["name"] if signals else ""
        debate_block = f"\n{sep}\n🤖 AI議論【{top_name}】 Bull/Bear/Quant\n{debate_data[:600]}"

    # API残量
    api_block = get_status_report()

    # リスク管理
    order_amount = ACCOUNT_BALANCE * RiskManager.MAX_SINGLE_POSITION
    risk_lines = []
    for s in signals:
        ok, reason = rm.check_before_order(s["code"], order_amount, ACCOUNT_BALANCE)
        icon = "✅" if ok else "🚫"
        risk_lines.append(f"  {icon} {s['name']}({s['code']}): {reason}")
    risk_block = "🛡 注文可否\n" + "\n".join(risk_lines)

    # EDINET（重要開示があれば）
    edinet_block = ""
    if edinet_data and "特記事項なし" not in edinet_data and len(edinet_data) > 20:
        edinet_block = f"\n{sep}\n📋 適時開示\n{edinet_data[:400]}"

    full_message = "\n\n".join(filter(None, [
        header,
        top_picks,
        market_snapshot,
        stocks_snapshot,
        volume_scan,
        sep,
        news_block,
        sep,
        detail_block,
        debate_block,
        edinet_block,
        sep,
        risk_block,
        sep,
        api_block,
    ]))

    print("Step 6: Discord送信中...")
    send_discord(full_message)
    print("完了。")


if __name__ == "__main__":
    main()
