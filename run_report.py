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
from market_data import format_macro_snapshot, format_stocks_snapshot, format_news_ddg

load_dotenv()

WATCHLIST = [
    {"code": "7203", "name": "トヨタ自動車"},
    {"code": "6758", "name": "ソニーグループ"},
    {"code": "9984", "name": "ソフトバンクグループ"},
    {"code": "4063", "name": "信越化学工業"},
]

# 口座残高（環境変数で管理。週次で手動更新）
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000000"))


def macro_scan(tavily: TavilyClient) -> str:
    queries = [
        "geopolitical risk stock market today",
        "Federal Reserve interest rate June 2026",
        "Nikkei 225 USD JPY today",
    ]
    results = []
    for q in queries:
        r = tavily.search(q, max_results=2)
        for item in r.get("results", []):
            results.append(f"- {item['title']}: {item['content'][:200]}")
    return "\n".join(results)


def company_scan(exa: Exa, stock: dict) -> str:
    r = exa.search_and_contents(
        f"{stock['name']} 株価 ニュース 2026年6月",
        num_results=2,
        text={"max_characters": 300},
    )
    snippets = [f"- {res.title}: {res.text[:200]}" for res in r.results]
    return "\n".join(snippets)


def send_discord(message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or "xxxx" in url:
        print("[Discord未設定] レポート出力:\n", message)
        return
    # 2000文字超の場合は分割して送信
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for chunk in chunks:
        requests.post(url, json={"content": chunk}, timeout=10)


def _build_risk_block(rm: RiskManager) -> str:
    """注文可否チェック結果ブロックを生成"""
    lines = [rm.status_report(), "", "📋 銘柄別 注文可否（本日）"]
    # 1銘柄あたり残高15%相当の注文額でチェック
    order_amount = ACCOUNT_BALANCE * RiskManager.MAX_SINGLE_POSITION
    for stock in WATCHLIST:
        ok, reason = rm.check_before_order(stock["code"], order_amount, ACCOUNT_BALANCE)
        icon = "✅" if ok else "🚫"
        lines.append(f"  {icon} {stock['name']}({stock['code']}): {reason}")
    return "\n".join(lines)


def main():
    today = datetime.date.today().strftime("%Y/%m/%d")
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    exa = Exa(api_key=os.getenv("EXA_API_KEY"))

    # ── リスクマネージャー初期化 ──────────────────────────────
    rm = RiskManager()
    risk_status = rm.status_report()
    trading_ok = rm.check_before_order("_", ACCOUNT_BALANCE * 0.1, ACCOUNT_BALANCE)[0]
    print(risk_status)

    print("Step 1: マクロ環境スキャン中...")
    # yfinance（無料・リアルタイム）
    market_snapshot = format_macro_snapshot()
    stocks_snapshot = format_stocks_snapshot([s["code"] for s in WATCHLIST])
    # DDG追加ニュース（Tavily補完、無料）
    ddg_news = format_news_ddg([
        "Nikkei 225 stock market today",
        "Japan yen dollar exchange rate today",
        "Federal Reserve interest rate policy",
    ])
    # Tavily（詳細検索）
    macro_data = macro_scan(tavily)

    print("Step 2: 監視銘柄スキャン中...")
    company_data = ""
    for stock in WATCHLIST:
        news = company_scan(exa, stock)
        company_data += f"\n【{stock['name']}({stock['code']})】\n{news}\n"

    print("Step 2b: 適時開示スキャン中（EDINET）...")
    edinet_data = edinet_scan(WATCHLIST)

    print("Step 2c: テクニカル指標計算中（J-Quants）...")
    technical_data = ""
    for stock in WATCHLIST:
        result = technical_scan(stock["code"])
        technical_data += f"\n{result}\n"
        time.sleep(5)

    print("Step 2d: マルチエージェント議論中...")
    debate_data = ""
    for stock in WATCHLIST[:2]:  # 上位2銘柄のみ（API呼び出し節約）
        ctx = f"マクロ: {macro_data[:300]}\nニュース: {company_data[:300]}\nテクニカル: {technical_data[:300]}"
        debate = multi_agent_debate(stock["code"], stock["name"], ctx)
        debate_data += f"\n{debate}\n"

    print("Step 3: AI分析・レポート生成中...")
    trading_flag = "⛔ 本日は取引停止中" if not trading_ok else "✅ 取引可能"
    prompt = f"""あなたは日本株のAI投資アナリストです。以下のデータを分析してレポートを生成してください。

## リスク管理状態
{risk_status}
取引ステータス: {trading_flag}

## マーケットスナップショット（リアルタイム）
{market_snapshot}

{stocks_snapshot}

## マクロニュース（DuckDuckGo）
{ddg_news}

## マクロ環境詳細（Tavily）
{macro_data}

## 監視銘柄ニュース
{company_data}

## 適時開示・IR情報（EDINET）
{edinet_data}

## テクニカル指標（RSI・MACD・ボリンジャーバンド）
{technical_data}

## マルチエージェント議論結果（Bull/Bear/Quant）
{debate_data}

## 出力形式（必ずこの形式で）
📊 AI予測取引レポート【{today}】

📋 適時開示サマリー
・[重要開示があれば記載、なければ「特記事項なし」]

🌍 本日のマクロ環境
・総合スコア: X/5（リスクオン/中立/オフ）
・注目: [最重要ニュース1行]

📉 テクニカルサマリー
・RSI過熱/割安: [銘柄名と数値]
・MACD方向性: [各銘柄の強気/弱気]
・BB位置: [バンド内/上限/下限付近]

🎯 本日のアクション候補
{"【⛔ 取引停止中 — 以下は参考情報のみ】" if not trading_ok else ""}
【買い候補】（ファンダ＋テクニカル根拠付きで）
【様子見】（理由付きで）

⚠️ 注意事項（3点以内）

📈 今後1週間の見通し（2〜3文）
"""
    report = chat(prompt, provider="groq")

    # リスクブロックをレポート末尾に追加
    risk_block = _build_risk_block(rm)
    full_message = f"{report}\n\n---\n🛡 リスク管理ステータス\n{risk_block}"

    print("Step 4: Discord送信中...")
    send_discord(full_message)
    print("完了。")


if __name__ == "__main__":
    main()
