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
./translator-ui.sh
```

Windows PowerShell では次を実行します。

```powershell
.\translator-ui.ps1
```

Windows PowerShell 5 で Execution Policy により読み込みが拒否される場合は、ポリシーを恒久変更せず、
その起動だけ次のように実行できます。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\translator-ui.ps1
```

組織のグループポリシーがこれを禁止する場合は、そのポリシーに従ってください。ダウンロードしたリポジトリーでは、
ポリシーが `RemoteSigned` の場合に限り `Unblock-File .\translator-ui.ps1` も選択肢です。

ラッパーは `uv run --locked` を優先してロック済み環境を解決してから、その環境のPythonでlauncherを直接起動します。
これにより `Ctrl+C` はuvの中継ではなくlauncherへ届きます。uv がない場合は既存の `.venv` を使い、`.venv` も
ない場合は依存関係がすでにある Python 3.12 以上だけを利用します。グローバル Python 環境へ依存関係を導入する
ことはありません。

サービスは `127.0.0.1:4568` にバインドします。ヘルスチェック成功後にブラウザーを開くには、
macOS/Linux/WSL では `--open-browser`、PowerShell では `-OpenBrowser` を指定してください。

ANSI対応の対話端末では、起動ラッパーが簡易TUIを表示します。`q` の後に `y` を押すと TranslatorUI の
サーバーだけを終了し、`o` はUIを再度ブラウザーで開きます。`h` または `?` はヘルプ、`j` / `k` / `f` は
メモリー上のサーバーログの閲覧／末尾追従です。`Ctrl+C` でも安全に停止できます。launcherがブラウザーを閉じる
ことはありません。macOS/Linux/WSL では `--no-tui`、PowerShell では `-NoTui` を指定すると前景ログ表示に
戻ります。非対話起動に加え、Windows上の VS Code 統合ターミナルでは `Ctrl+C` を確実に扱うため、自動的に
launcherを迂回してUvicornを直接前景起動します。TUIはWindows Terminalまたは外部の対応端末で利用してください。
WSLでは `--open-browser` と `o` が `wslview`、次に `cmd.exe /c start` を使ってWindows側の既定ブラウザーを
開きます。

### Windows と WSL で同じチェックアウトを使う場合

Windows用とLinux用の仮想環境は互換ではありません。同じリポジトリーを `/mnt/<drive>/...` 経由でWSLから開き、
両方の環境で既定の `.venv` を使うと、WSL側の `uv` がWindows用の `.venv` をLinux用に置き換えることがあります。
Windows側の `uv` はそのLinux用リンクを削除できず、`failed to remove file '.venv/lib64'` で停止します。

最も安全なのはWindows用とWSL用に別のチェックアウトを使うことです。同じチェックアウトが必要な場合は、各環境で
仮想環境名を分離してから起動してください。

```powershell
# Windows PowerShell: リポジトリーのルートで実行
$env:UV_PROJECT_ENVIRONMENT = ".venv-win"
.\translator-ui.ps1
```

```bash
# WSL: 同じチェックアウトのルートで実行
export UV_PROJECT_ENVIRONMENT=.venv-linux
./translator-ui.sh
```

`.venv-win` と `.venv-linux` はGit管理外です。各端末でこの環境変数を設定した状態で `uv sync --locked` を
一度実行しておくこともできます。

既定の `.venv` がすでにWSL用に置き換わった場合は、**すべてのTranslatorUI・Python・uvプロセスを終了してから**、
まずWindows側で `.venv` フォルダーだけを削除し、起動ラッパーを再実行します。`uv run --locked` がWindows用の
環境を自動作成するため、通常は手動の `uv sync` は不要です。この削除対象はPython仮想環境だけであり、
ソースコード、`.env`、`translator-ui.toml` は削除しません。

```powershell
# Windows PowerShell: リポジトリーのルートで実行
if (-not (Test-Path -LiteralPath .\pyproject.toml)) { throw "Run this from the repository root." }
Remove-Item -LiteralPath .\.venv -Recurse -Force
.\translator-ui.ps1
```

Windows側の削除が `failed to remove file '.venv/lib64'` やアクセス拒否で失敗した場合だけ、WSLで対象リポジトリーの
ルートであることを確認して次を実行します。

```bash
pwd
test -f pyproject.toml && test -d .venv || exit 1
rm -rf -- .venv
```

その後、Windows PowerShellでリポジトリーのルートに戻り、起動ラッパーを再実行します。

```powershell
.\translator-ui.ps1
```

## プロバイダー設定

複数プロバイダーを使う場合は、`translator-ui.toml.example` を `translator-ui.toml` にコピーして、
`.env` に `TRANSLATOR_UI_CONFIG=translator-ui.toml` を設定します。API キーは `.env` に置き、TOML には
`api_key_env = "OPENAI_COMPAT_API_KEY"` のように環境変数名だけを記載します。

UI で選択できるのは有効な `openai_compatible` プロバイダーだけです。ACP の設定は TOML に予約できますが、
プロセス隔離を含む専用アダプターを別途設計・実装するまで UI には表示しません。

各Providerは従来どおりの `model` を使うか、`[[providers.models]]` で複数モデルを定義できます。モデルごとに
`efforts` と `effort_request_field` を定義した場合だけ、選択したeffortを上流へ送ります。画面の
「設定を再読み込み」はアプリケーションを再起動せずに `.env` と選択中のTOMLを読み直します。親プロセスの
環境変数は `.env` より優先され、再読込に失敗しても稼働中の設定は変更されません。

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
