"""
マルチエージェント議論モジュール
TradingAgentsライブラリの代替として、Groq LLMで複数アナリスト視点を実装。

3エージェント:
  - Bull (強気派): ポジティブ材料に注目
  - Bear (弱気派): リスク・ネガティブ材料に注目
  - Quant (定量派): テクニカル指標・数値ベース分析

使い方:
  from multi_agent import multi_agent_debate
  conclusion = multi_agent_debate(stock_code, stock_name, context_data)
"""
import os
from dotenv import load_dotenv

load_dotenv()

AGENTS = {
    "bull": {
        "name": "強気アナリスト(Bull)",
        "role": "あなたは楽観的な株式アナリストです。ポジティブな材料、成長要因、買いシグナルに注目して分析してください。",
    },
    "bear": {
        "name": "弱気アナリスト(Bear)",
        "role": "あなたは慎重な株式アナリストです。リスク要因、ネガティブ材料、売りシグナルに注目して分析してください。",
    },
    "quant": {
        "name": "定量アナリスト(Quant)",
        "role": "あなたは定量分析の専門家です。テクニカル指標・数値・統計に基づいて客観的に分析してください。感情的な判断は排除します。",
    },
}


def _call_agent(agent_key: str, stock_name: str, code: str, context: str) -> str:
    """単一エージェントに分析を依頼"""
    try:
        from llm_client import chat
        agent = AGENTS[agent_key]
        prompt = f"""{agent['role']}

以下のデータをもとに{stock_name}({code})について分析してください（3〜5文で簡潔に）。

{context}

【{agent['name']}の見解】"""
        return chat(prompt, provider="groq")
    except Exception as e:
        return f"[{AGENTS[agent_key]['name']} エラー: {e}]"


def _synthesize(stock_name: str, code: str,
                bull_view: str, bear_view: str, quant_view: str) -> str:
    """3エージェントの議論を統合して結論を出す"""
    try:
        from llm_client import chat
        prompt = f"""あなたは投資判断の最終意思決定者です。3人のアナリストの見解を統合して結論を出してください。

## {stock_name}({code}) アナリスト議論

【強気派】
{bull_view}

【弱気派】
{bear_view}

【定量派】
{quant_view}

## 統合結論（必ずこの形式で）
判断: [強い買い / 買い / 中立 / 売り / 強い売り]
確信度: X/5
根拠: [1〜2文]
リスク: [1文]"""
        return chat(prompt, provider="groq")
    except Exception as e:
        return f"[統合エラー: {e}]"


def multi_agent_debate(code: str, stock_name: str, context: str) -> str:
    """
    3エージェントによる議論を実行し、統合結論を返す。

    Args:
        code: 銘柄コード (例: "7203")
        stock_name: 銘柄名 (例: "トヨタ自動車")
        context: マクロ・ニュース・テクニカルデータの文字列

    Returns:
        議論結果と統合結論を含む文字列
    """
    lines = [f"🤖 マルチエージェント議論: {stock_name}({code})", ""]

    bull = _call_agent("bull", stock_name, code, context)
    lines.append(f"📈 強気派: {bull}")
    lines.append("")

    bear = _call_agent("bear", stock_name, code, context)
    lines.append(f"📉 弱気派: {bear}")
    lines.append("")

    quant = _call_agent("quant", stock_name, code, context)
    lines.append(f"📊 定量派: {quant}")
    lines.append("")

    conclusion = _synthesize(stock_name, code, bull, bear, quant)
    lines.append(f"⚖️ 統合結論:\n{conclusion}")

    return "\n".join(lines)


if __name__ == "__main__":
    # テスト実行
    test_context = """
マクロ: 米FRBは利上げ停止を示唆。円安傾向継続(150円/ドル)。
ニュース: トヨタ、2026年度EV販売目標を30万台に引き上げ。HV好調継続。
テクニカル: RSI=45(中立)、MACD=+12(強気)、BB=中央付近。
    """
    result = multi_agent_debate("7203", "トヨタ自動車", test_context)
    print(result)
