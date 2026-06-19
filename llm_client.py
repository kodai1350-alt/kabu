import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.json"


class LLMError(Exception):
    pass


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _call_anthropic(prompt: str, model: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY が .env に設定されていません")
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_gemini(prompt: str, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY が .env に設定されていません")
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


def _call_groq(prompt: str, model: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY が .env に設定されていません")
    from groq import Groq
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def chat(prompt: str, provider: str | None = None) -> str:
    config = _load_config()
    active_provider = provider or config["provider"]
    model = config["models"][active_provider]

    if active_provider == "anthropic":
        return _call_anthropic(prompt, model)
    elif active_provider == "gemini":
        return _call_gemini(prompt, model)
    elif active_provider == "groq":
        return _call_groq(prompt, model)
    else:
        raise LLMError(f"未知のプロバイダー: {active_provider}。'anthropic', 'gemini', 'groq' のいずれかを指定してください")
