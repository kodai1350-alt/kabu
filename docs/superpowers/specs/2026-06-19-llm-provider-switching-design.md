# LLMプロバイダー切り替え機能 設計仕様

## 概要

AnthropicとGeminiの両APIを使用可能にし、CLIコマンドで切り替えられる統一LLMクライアントを実装する。株の売買判断・ニュース要約・財務分析すべてで共通インターフェースを使用する。

## 要件

- AnthropicとGemini両方のAPIを呼び出せる
- `python set_provider.py <provider>` で永続的に切り替え可能
- `--provider` フラグで1回だけ別プロバイダーを使える
- どちらのプロバイダーでも呼び出し元コードは変わらない

## ファイル構成

```
kabu/
├── .env                  # ANTHROPIC_API_KEY, GEMINI_API_KEY
├── .env.example          # テンプレート
├── config.json           # アクティブプロバイダーと使用モデル
├── llm_client.py         # 統一LLMクライアント
├── set_provider.py       # 切り替えCLI
└── requirements.txt      # anthropic, google-generativeai
```

## config.json スキーマ

```json
{
  "provider": "gemini",
  "models": {
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.0-flash"
  }
}
```

- `provider`: 現在アクティブなプロバイダー（`"anthropic"` または `"gemini"`）
- `models`: プロバイダーごとに使用するモデルID

## llm_client.py インターフェース

```python
def chat(prompt: str, provider: str | None = None) -> str:
    """
    プロンプトを送信してテキストを返す。
    provider が None の場合は config.json の設定を使用。
    """
```

- 戻り値は常に `str`（どちらのAPIでも統一）
- エラー時は `LLMError` を raise
- `provider` 引数で `--provider` フラグからの上書きを受け付ける

## set_provider.py 仕様

```bash
python set_provider.py gemini       # config.json を更新して切り替え
python set_provider.py anthropic    # config.json を更新して切り替え
python set_provider.py status       # 現在の設定を表示
```

- 不正なプロバイダー名は即座にエラーメッセージを出して終了
- 切り替え後は現在のプロバイダーとモデルを表示して確認

## 使用モデル

| プロバイダー | モデル | 特徴 |
|---|---|---|
| Anthropic | claude-sonnet-4-6 | 高精度・有料 |
| Gemini | gemini-2.0-flash | 無料枠・高速 |

## エラーハンドリング

- APIキー未設定：起動時に検出してエラーメッセージ
- APIエラー（レートリミット等）：エラー内容をそのまま表示
- 自動フォールバックは行わない（明示的な切り替えのみ）

## 依存パッケージ

```
anthropic>=0.40.0
google-generativeai>=0.8.0
python-dotenv>=1.0.0
```
