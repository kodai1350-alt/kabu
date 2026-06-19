import os
import datetime
import requests
from dotenv import load_dotenv
from tavily import TavilyClient
from exa_py import Exa
from llm_client import chat

load_dotenv()

WATCHLIST = [
    {"code": "7203", "name": "トヨタ自動車"},
    {"code": "6758", "name": "ソニーグループ"},
    {"code": "9984", "name": "ソフトバンクグループ"},
    {"code": "4063", "name": "信越化学工業"},
]


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
    requests.post(url, json={"content": message[:2000]}, timeout=10)


def main():
    today = datetime.date.today().strftime("%Y/%m/%d")
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    exa = Exa(api_key=os.getenv("EXA_API_KEY"))

    print("Step 1: マクロ環境スキャン中...")
    macro_data = macro_scan(tavily)

    print("Step 2: 監視銘柄スキャン中...")
    company_data = ""
    for stock in WATCHLIST:
        news = company_scan(exa, stock)
        company_data += f"\n【{stock['name']}({stock['code']})】\n{news}\n"

    print("Step 3: AI分析・レポート生成中...")
    prompt = f"""あなたは日本株のAI投資アナリストです。以下のデータを分析してレポートを生成してください。

## マクロ環境データ
{macro_data}

## 監視銘柄ニュース
{company_data}

## 出力形式（必ずこの形式で）
📊 AI予測取引レポート【{today}】

🌍 本日のマクロ環境
・総合スコア: X/5（リスクオン/中立/オフ）
・注目: [最重要ニュース1行]

🎯 本日のアクション候補
【買い候補】（根拠付きで）
【様子見】（理由付きで）

⚠️ 注意事項（3点以内）

📈 今後1週間の見通し（2〜3文）
"""
    report = chat(prompt, provider="groq")

    print("Step 4: Discord送信中...")
    send_discord(report)
    print("完了。")


if __name__ == "__main__":
    main()
