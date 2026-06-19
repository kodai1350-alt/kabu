import json
import pytest
from unittest.mock import patch
from pathlib import Path
import set_provider


def test_set_provider_updates_config(tmp_path):
    """set_provider('gemini') でconfig.jsonのproviderが更新される"""
    config = {"provider": "anthropic", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch.object(set_provider, "CONFIG_PATH", config_file):
        set_provider.set_provider("gemini")

    result = json.loads(config_file.read_text())
    assert result["provider"] == "gemini"


def test_set_provider_invalid_raises(tmp_path):
    """不正なプロバイダー名はSystemExitを発生させる"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch.object(set_provider, "CONFIG_PATH", config_file):
        with pytest.raises(SystemExit):
            set_provider.set_provider("openai")


def test_status_shows_current_provider(tmp_path, capsys):
    """status() で現在のプロバイダーとモデルが表示される"""
    config = {"provider": "gemini", "models": {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.0-flash"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))

    with patch.object(set_provider, "CONFIG_PATH", config_file):
        set_provider.status()

    captured = capsys.readouterr()
    assert "gemini" in captured.out
    assert "gemini-2.0-flash" in captured.out
