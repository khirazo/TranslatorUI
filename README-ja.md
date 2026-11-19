# TranslatorUI

TranslatorUI は、OpenAI 互換 LLM エンドポイントを使って逐次テキスト翻訳を行うローカル Web UI です。
LM Studio をはじめとする互換プロバイダーに対応します。PDF 翻訳は意図的に対象外であり、このリポジトリーは
PDFMathTranslate を取得・同梱・実行しません。

本プロジェクトは MIT ライセンスの LocaLingo を基にしており、MIT ライセンスは
[`LICENSE`](LICENSE) に保持しています。

## ローカル起動

[uv](https://docs.astral.sh/uv/) を導入し、`.env.template` を `.env` にコピーして、LLM サーバーが
公開するモデル ID と接続先を設定します。`LLM_ENDPOINT` は `/v1` を含まないルート URL です。

```bash
./start-translator-ui.sh
```

Windows PowerShell では次を実行します。

```powershell
.\start-translator-ui.ps1
```

ラッパーは `uv run --locked` を優先します。uv がない場合は既存の `.venv` を使い、`.venv` もない場合は
依存関係がすでにある Python 3.12 以上だけを利用します。グローバル Python 環境へ依存関係を導入することは
ありません。

サービスは `127.0.0.1:4568` にバインドします。ヘルスチェック成功後にブラウザーを開くには、
macOS/Linux/WSL では `--open-browser`、PowerShell では `-OpenBrowser` を指定してください。

## プロバイダー設定

複数プロバイダーを使う場合は、`translator-ui.toml.example` を `translator-ui.toml` にコピーして、
`.env` に `TRANSLATOR_UI_CONFIG=translator-ui.toml` を設定します。API キーは `.env` に置き、TOML には
`api_key_env = "OPENAI_COMPAT_API_KEY"` のように環境変数名だけを記載します。

UI で選択できるのは有効な `openai_compatible` プロバイダーだけです。ACP の設定は TOML に予約できますが、
プロセス隔離を含む専用アダプターを別途設計・実装するまで UI には表示しません。

## Docker Compose

Compose は任意であり、TranslatorUI サービスだけを起動します。

```bash
docker compose up -d translator-ui
```

`TRANSLATOR_UI_CONFIG` のパスはホスト上の TOML ファイルを指します。Compose はこれをコンテナー内の
`/app/translator-ui.toml` に読み取り専用でマウントするため、起動前に TOML を作成してください。

## 確認

```bash
curl http://localhost:4568/health
```

期待する応答は `{"status":"ok"}` です。翻訳要求は同一オリジンの `/api/translate-text` に送られ、
Server-Sent Events で逐次返却されます。
