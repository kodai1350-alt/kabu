# LLMプロバイダー切り替え機能 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AnthropicとGemini両APIを統一インターフェースで使えるようにし、CLIコマンドで切り替えられるようにする

**Architecture:** `llm_client.py` が唯一のLLM呼び出し口となり、`config.json` に保存されたプロバイダー設定を読んで内部でAnthropicかGeminiを切り替える。`set_provider.py` は `config.json` を更新するだけのシンプルなCLIツール。

**Tech Stack:** Python 3.14, anthropic>=0.40.0, google-generativeai>=0.8.0, python-dotenv>=1.0.0, pytest

## Global Constraints

- Python 3.10以上必須
- APIキーは必ず `.env` から読み込む（コードに直書き禁止）
- 自動フォールバックは実装しない（明示的切り替えのみ）
- 戻り値は常に `str`

---

## ファイルマップ

| ファイル | 役割 |
|---|---|
| `requirements.txt` | 依存パッケージ |
| `.env.example` | APIキーテンプレート（Gemini追加） |
| `config.json` | アクティブプロバイダーと使用モデル |
| `llm_client.py` | 統一LLMクライアント（核心） |
| `set_provider.py` | プロバイダー切り替えCLI |
| `tests/test_llm_client.py` | llm_client のユニットテスト |
| `tests/test_set_provider.py` | set_provider のユニットテスト |

---

### Task 1: 依存関係と設定ファイルのセットアップ

**Files:**
- Create: `requirements.txt`
- Modify: `.env.example`
- Create: `config.json`

**Interfaces:**
- Produces: `config.json` スキーマ（Task 2, 3が読み込む）

- [ ] **Step 1: requirements.txt を作成する**

```
anthropic>=0.40.0
google-generativeai>=0.8.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

ファイルパス: `requirements.txt`

- [ ] **Step 2: パッケージをインストールする**

```bash
pip install -r requirements.txt
```

期待する出力: `Successfully installed anthropic-... google-generativeai-... python-dotenv-...`

- [ ] **Step 3: .env.example に Gemini キーを追加する**

[.env.example](.env.example) の `# === Claude ===` ブロックを以下に置き換える:

```
# === LLM プロバイダー ===
# どちらか一方だけでも動作する
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
GEMINI_API_KEY=AIzaxxxxxxxxxxxx
```

- [ ] **Step 4: config.json を作成する**

```json
{
  "provider": "gemini",
  "models": {
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.0-flash"
  }
}
```

ファイルパス: `config.json`

- [ ] **Step 5: .gitignore に .env を確認する**

[.gitignore](.gitignore) に `.env` が含まれていることを確認。含まれていれば何もしない。

- [ ] **Step 6: コミットする**

```bash
git add requirements.txt .env.example config.json .gitignore
git commit -m "feat: add LLM provider config and dependencies"
```

---

### Task 2: llm_client.py の実装（テスト駆動）

**Files:**
- Create: `tests/test_llm_client.py`
- Create: `llm_client.py`

**Interfaces:**
- Consumes: `config.json`（Task 1が作成）、`.env`の`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`
- Produces:
  - `chat(prompt: str, provider: str | None = None) -> str`
  - `class LLMError(Exception)`

- [ ] **Step 1: テストディレクトリを作成する**

```bash
mkdir tests
```

- [ ] **Step 2: 失敗するテストを書く**

ファイルパス: `tests/test_llm_client.py`

```python
import json
import pytest
from unittest.mock import patch, MagicMock


def test_chat_uses_config_provider(tmp_path, monkeypatch):
    """config.jsonのプロバイダーを使ってchatが呼ばれる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    with patch("llm_client.CONFIG_PATH", str(config_file)):
        with patch("llm_client._call_gemini", return_value="Geminiの回答") as mock_gemini:
            from importlib import reload
            import llm_client
            reload(llm_client)
            result = llm_client.chat("テスト")
            mock_gemini.assert_called_once_with("テスト", "gemini-2.0-flash")
            assert result == "Geminiの回答"


def test_chat_provider_override(tmp_path, monkeypatch):
    """--provider引数でconfig.jsonを上書きできる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    with patch("llm_client.CONFIG_PATH", str(config_file)):
        with patch("llm_client._call_anthropic", return_value="Claudeの回答") as mock_anthropic:
            from importlib import reload
            import llm_client
            reload(llm_client)
            result = llm_client.chat("テスト", provider="anthropic")
            mock_anthropic.assert_called_once_with("テスト", "claude-sonnet-4-6")
            assert result == "Claudeの回答"


def test_chat_raises_llm_error_on_missing_key(tmp_path, monkeypatch):
    """APIキー未設定時はLLMErrorを投げる"""
    config = {"provider": "anthropic", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("llm_client.CONFIG_PATH", str(config_file)):
        from importlib import reload
        import llm_client
        reload(llm_client)
        with pytest.raises(llm_client.LLMError, match="ANTHROPIC_API_KEY"):
            llm_client.chat("テスト")
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
pytest tests/test_llm_client.py -v
```

期待する出力: `ModuleNotFoundError: No module named 'llm_client'`

- [ ] **Step 4: llm_client.py を実装する**

ファイルパス: `llm_client.py`

```python
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
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel(model)
    response = gemini_model.generate_content(prompt)
    return response.text


def chat(prompt: str, provider: str | None = None) -> str:
    config = _load_config()
    active_provider = provider or config["provider"]
    model = config["models"][active_provider]

    if active_provider == "anthropic":
        return _call_anthropic(prompt, model)
    elif active_provider == "gemini":
        return _call_gemini(prompt, model)
    else:
        raise LLMError(f"未知のプロバイダー: {active_provider}。'anthropic' か 'gemini' を指定してください")
```

- [ ] **Step 5: テストがパスすることを確認する**

```bash
pytest tests/test_llm_client.py -v
```

期待する出力: `3 passed`

- [ ] **Step 6: コミットする**

```bash
git add llm_client.py tests/test_llm_client.py
git commit -m "feat: add unified LLM client with Anthropic and Gemini support"
```

---

### Task 3: set_provider.py の実装（テスト駆動）

**Files:**
- Create: `tests/test_set_provider.py`
- Create: `set_provider.py`

**Interfaces:**
- Consumes: `config.json`（Task 1が作成）
- Produces: `set_provider.py` — コマンドライン実行で `config.json` を更新する

- [ ] **Step 1: 失敗するテストを書く**

ファイルパス: `tests/test_set_provider.py`

```python
import json
import pytest
from unittest.mock import patch
from pathlib import Path


def test_set_provider_updates_config(tmp_path):
    """set_provider gemini でconfig.jsonのproviderが更新される"""
    config = {"provider": "anthropic", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch("set_provider.CONFIG_PATH", config_file):
        import set_provider
        from importlib import reload
        reload(set_provider)
        set_provider.set_provider("gemini")

    result = json.loads(config_file.read_text())
    assert result["provider"] == "gemini"


def test_set_provider_invalid_raises(tmp_path):
    """不正なプロバイダー名はSystemExitを発生させる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch("set_provider.CONFIG_PATH", config_file):
        import set_provider
        from importlib import reload
        reload(set_provider)
        with pytest.raises(SystemExit):
            set_provider.set_provider("openai")


def test_status_shows_current_provider(tmp_path, capsys):
    """status コマンドで現在のプロバイダーとモデルが表示される"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch("set_provider.CONFIG_PATH", config_file):
        import set_provider
        from importlib import reload
        reload(set_provider)
        set_provider.status()

    captured = capsys.readouterr()
    assert "gemini" in captured.out
    assert "gemini-2.0-flash" in captured.out
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_set_provider.py -v
```

期待する出力: `ModuleNotFoundError: No module named 'set_provider'`

- [ ] **Step 3: set_provider.py を実装する**

ファイルパス: `set_provider.py`

```python
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
```

- [ ] **Step 4: テストがパスすることを確認する**

```bash
pytest tests/test_set_provider.py -v
```

期待する出力: `3 passed`

- [ ] **Step 5: 全テストをまとめて実行する**

```bash
pytest tests/ -v
```

期待する出力: `6 passed`

- [ ] **Step 6: コミットする**

```bash
git add set_provider.py tests/test_set_provider.py
git commit -m "feat: add set_provider CLI for switching LLM providers"
```

---

### Task 4: 動作確認

**Files:**
- Modify: `.env`（手動でAPIキーを記入）

**Interfaces:**
- Consumes: `llm_client.chat()`、`set_provider`（Task 2, 3が作成）

- [ ] **Step 1: .env を作成してGeminiキーを記入する**

```bash
cp .env.example .env
```

`.env` を開いて `GEMINI_API_KEY=` に実際のキーを記入する（aistudio.google.com で取得）

- [ ] **Step 2: Geminiで動作確認する**

```bash
python -c "from llm_client import chat; print(chat('こんにちは。1文で返事して'))"
```

期待する出力: 日本語の短い返答

- [ ] **Step 3: プロバイダーをAnthropicに切り替えてステータス確認する**

```bash
python set_provider.py status
python set_provider.py anthropic
python set_provider.py status
```

期待する出力:
```
現在のプロバイダー: gemini（モデル: gemini-2.0-flash）
✓ プロバイダーを 'anthropic' に切り替えました（モデル: claude-sonnet-4-6）
現在のプロバイダー: anthropic（モデル: claude-sonnet-4-6）
```

- [ ] **Step 4: Geminiに戻す**

```bash
python set_provider.py gemini
```

- [ ] **Step 5: 最終コミット**

```bash
git add .
git commit -m "feat: LLM provider switching complete"
```
