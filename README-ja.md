# TranslatorUI
## スクリーンショット

![TranslatorUI のテキスト翻訳画面](docs/screenshot-text.png)

TranslatorUI は、OpenAI 互換 LLM エンドポイントを使って逐次テキスト翻訳を行うローカル Web UI です。
LM Studio をはじめとする互換プロバイダーに対応します。PDF 翻訳は意図的に対象外であり、このリポジトリーは
PDFMathTranslate を取得・同梱・実行しません。

本プロジェクトは MIT ライセンスの LocaLingo を基にしており、MIT ライセンスは
[`LICENSE`](LICENSE) に保持しています。upstream の帰属と来歴は [`NOTICE`](NOTICE) を参照してください。

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

Windows のデスクトップにショートカットを作成するには、`create-shortcut.cmd` をダブルクリックし、
画面の案内に従ってください。ショートカットはサーバーを起動し、準備完了後にブラウザーを開きます。
プロジェクトのフォルダーを移動した場合は、作成スクリプトを再実行して置き換えを確認してください。
この操作はショートカットの作成のみを行い、依存関係のインストールやプロバイダーの設定は行いません。
作成時とショートカットからの起動時には、そのプロセスに限り Execution Policy をバイパスします。
組織のポリシーで禁止されている場合は、そのポリシーに従ってください。
以前作成したショートカットには、作り直すと現在の起動設定が反映されます。

Windows PowerShell 5 で Execution Policy により読み込みが拒否される場合は、ポリシーを恒久変更せず、
その起動だけ次のように実行できます。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\translator-ui.ps1
```

組織のグループポリシーがこれを禁止する場合は、そのポリシーに従ってください。ダウンロードしたリポジトリーでは、
ポリシーが `RemoteSigned` の場合に限り `Unblock-File .\translator-ui.ps1` も選択肢です。

ラッパーは `uv run --locked` を優先してロック済み環境を解決し、その環境の Python でサーバーを前景起動します。
uv がない場合は既存の `.venv` を使い、`.venv` も
ない場合は依存関係がすでにある Python 3.12 以上だけを利用します。グローバル Python 環境へ依存関係を導入する
ことはありません。

サービスは `127.0.0.1:4568` にバインドします。ヘルスチェック成功後にブラウザーを開くには、
macOS/Linux/WSL では `--open-browser`、PowerShell では `-OpenBrowser` を指定してください。

サーバーは端末にログを表示します。停止するには `Ctrl+C` を押してください。専用ウィンドウから起動した場合は、
そのウィンドウを閉じても停止できます。WSL の `--open-browser` は `wslview` または `cmd.exe /c start` を使って
Windows 側の既定ブラウザーを開きます。

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

## 表示言語

**翻訳設定 → 表示言語**で英語・日本語を選べます。選択はブラウザーに保存されます。
`?locale=ja` のようなURL指定は、そのページだけで保存済みの選択に優先します。
どちらの指定もなければ、ブラウザーの対応言語を使い、該当しなければ英語で表示します。
画面の表示言語は、翻訳の原文言語・訳文言語とは独立しています。

## プロバイダー設定

複数プロバイダーを使う場合は、`translator-ui.toml.template` を `translator-ui.toml` にコピーして、
`.env` に `TRANSLATOR_UI_CONFIG=translator-ui.toml` を設定します。API キーは `.env` に置き、TOML には
`api_key_env = "OPENAI_COMPAT_API_KEY"` のように環境変数名だけを記載します。

有効な `openai_compatible` と ACP プロバイダーを UI で選択できます。ACP は既定で無効です。有効化する際は、
利用するエージェントが提供する場合だけ `mode = "ask"` を明示し、信頼できるローカル CLI だけを `command` 配列で指定してください。各翻訳は専用の
一時ワークスペースと新しい子プロセスで実行され、filesystem/terminal 能力は提供せず、permission 要求は拒否します。
モデルと effort はエージェントの capability から取得します。取得できないエージェントは「Agent default」として
エージェント既定のモデルで動作します。ACP 子プロセスへ渡す環境変数は実行に必要な最小限だけであり、追加が必要な
ネットワーク設定・認証の**変数名**だけを `environment` 配列に指定します。値を TOML に書かないでください。
意図しないエージェントセッションの重複を防ぐため、TranslatorUI は ACP 子プロセスを同時に 1 本だけ実行します。

`ask` は IBM Bob などが広告する mode の例です。Codex ACP wrapper は異なる mode 名を広告する場合があるため、
対応する mode が広告されていなければ `mode` を未指定にしてください。

ACP を有効にする前に、実際の stdio コマンドを確認してください。コーディング CLI が `<CLI> acp` を提供するとは
限りません。Codex では別ラッパーの `npx -y @agentclientprotocol/codex-acp@2.5.0` を利用できます。
これは翻訳の検証範囲が限定的な固定版なので、使用前に再検証が必要です。動作する ACP コマンドがなければ ACP Provider は
無効のままにし、OpenAI互換 Provider を利用してください。

各Providerは従来どおりの `model` を残したまま、`[[providers.model_overrides]]` で複数モデルの表示名と
モデル固有の `translation_profile`（例: `plamo3`）を定義できます。順序付きの
`[[providers.model_rules]]` は検証済み正規表現による補完規則であり、個別上書き、規則、Provider既定値の順に
適用されます。起動時と「設定を再読み込み」後に Provider の `/v1/models` を照会し、その時点で報告された
モデル ID だけを、このTOML metadata と合成してUIへ表示します。モデルごとに `efforts` と
`effort_request_field` を定義した場合だけ、選択したeffortを上流へ送ります。画面の「設定を再読み込み」は
アプリケーションを再起動せずに `.env` と選択中のTOMLを読み直します。親プロセスの
環境変数は `.env` より優先され、再読込に失敗しても稼働中の設定は変更されません。

`max_tokens` はモデルの文脈長ではなく出力上限です。Provider の既定値は 4,096 とし、特定モデルだけ
変更したい場合は `model_overrides` に `max_tokens` を指定します。モデル別の値が優先されます。入力と出力の
合計は、上流ランタイムで実際に設定された文脈長に収めてください。

名前付きの選択状態を profile として保存するには、`allow_profile_writes = true` を明示します。TranslatorUI は
接続設定TOMLや `.env` を書き換えず、固定の `translator-ui.profiles.toml`（または `profiles_file`）だけを
更新します。保存時は revision を照合し、一時ファイルから原子的に置換するため、一覧取得後に手編集された
profile を上書きしません。

`generic` 翻訳プロファイルは、モデルに依存しない翻訳指示を送り、XML、HTML、プレースホルダー、
コード構造を保持したまま自然言語部分を翻訳します。PLaMo 専用のプロンプトトークンや stop token は送りません。

画面は、選択したプロバイダー、モデル、effort、原文/訳文言語、日本語文体を、この origin のブラウザー
ローカルストレージに記憶します。原文・翻訳結果・API キー・接続先・設定値は保存しません。次回起動時は
現在の設定と照合し、利用できなくなった選択値を安全に既定値へ戻します。

## 翻訳履歴

翻訳履歴の保存は既定で無効です。有効にするには、`translator-ui.toml` の `[app]` に
`save_translations = true` を設定します。TOML を使わず、従来の `.env` で設定している場合は、
`SAVE_TRANSLATIONS=true` を指定してください。

最初の保存時に、プロジェクト直下に `data/translations.json` が作成されます。原文と訳文は
平文の JSON として記録されます。

## プロキシー設定

TranslatorUI から OpenAI 互換 LLM への上流要求は、HTTPX の標準プロキシー環境変数
`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` を使用します。`.env.template` のコメント付き例を
Git 管理外の `.env` へコピーし、ネットワークに必要な変数だけを設定してください。一般的な HTTP forward
proxy では、LLM エンドポイント自体が HTTPS でも proxy URL は `http://` を指定します。LM Studio への
ローカル通信を proxy から除外するには、次を設定します。

```dotenv
NO_PROXY=localhost,127.0.0.1,::1
```

proxy URL に資格情報を含める場合、その URL は秘密情報です。実値は `.env` または起動プロセスの環境変数に
だけ置き、`translator-ui.toml`、文書、ログ、コミットには入れないでください。proxy の挙動と認証の互換性は
HTTPX および設定した proxy に従います。proxy はプロセス全体に適用され、現在は Provider ごとには選択できません。

## 確認

```bash
curl http://localhost:4568/health
```

期待する応答は `{"status":"ok"}` です。翻訳要求は同一オリジンの `/api/translate-text` に送られ、
Server-Sent Events で逐次返却されます。

## ライセンスと帰属

TranslatorUI は MIT ライセンスの [LocaLingo](https://github.com/soukouki/LocaLingo) を基にしています。
upstream の著作権表示と MIT ライセンス文は [`LICENSE`](LICENSE) に保持し、採用した基準コミットと
upstream 由来部分の来歴は [`NOTICE`](NOTICE) に記録しています。
