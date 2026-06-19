import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
VALID_PROVIDERS = ("anthropic", "gemini")


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def set_provider(provider: str) -> None:
    if provider not in VALID_PROVIDERS:
        print(f"エラー: '{provider}' は無効です。使用可能: {', '.join(VALID_PROVIDERS)}")
        sys.exit(1)
    config = _load_config()
    config["provider"] = provider
    _save_config(config)
    model = config["models"][provider]
    print(f"✓ プロバイダーを '{provider}' に切り替えました（モデル: {model}）")


def status() -> None:
    config = _load_config()
    provider = config["provider"]
    model = config["models"][provider]
    print(f"現在のプロバイダー: {provider}（モデル: {model}）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python set_provider.py <gemini|anthropic|status>")
        sys.exit(1)

    command = sys.argv[1]
    if command == "status":
        status()
    else:
        set_provider(command)
