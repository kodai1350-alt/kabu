import json
import pytest
from unittest.mock import patch
import llm_client


def test_chat_uses_config_provider(tmp_path, monkeypatch):
    """config.jsonのプロバイダーを使ってchatが呼ばれる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr(llm_client, "CONFIG_PATH", config_file)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    with patch.object(llm_client, "_call_gemini", return_value="Geminiの回答") as mock_gemini:
        result = llm_client.chat("テスト")
        mock_gemini.assert_called_once_with("テスト", "gemini-2.0-flash")
        assert result == "Geminiの回答"


def test_chat_provider_override(tmp_path, monkeypatch):
    """provider引数でconfig.jsonを上書きできる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr(llm_client, "CONFIG_PATH", config_file)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    with patch.object(llm_client, "_call_anthropic", return_value="Claudeの回答") as mock_anthropic:
        result = llm_client.chat("テスト", provider="anthropic")
        mock_anthropic.assert_called_once_with("テスト", "claude-sonnet-4-6")
        assert result == "Claudeの回答"


def test_chat_raises_llm_error_on_missing_key(tmp_path, monkeypatch):
    """APIキー未設定時はLLMErrorを投げる"""
    config = {"provider": "anthropic", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr(llm_client, "CONFIG_PATH", config_file)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(llm_client.LLMError, match="ANTHROPIC_API_KEY"):
        llm_client.chat("テスト")
