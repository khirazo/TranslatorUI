
# LocaLingo

LocaLingoは、Preferred Networksによって開発された翻訳向け特化型大規模言語モデルであるPLaMo翻訳モデルを利用した、翻訳WebUIです。LM StudioやOllamaなどのOpenAI互換APIを持ったローカルLLMサーバーと連携して動作します。

![LocaLingo Screenshot](docs/screenshot-text.png)

テキストの翻訳だけでなく、PDFファイルの翻訳にも対応しています。PDFMathTranslateというライブラリを利用し、フォーマットを維持したまま翻訳を行います。PDF中に画像や図表が含まれていても問題ありません。(ただし、画像中の文字は翻訳されません。)

![LocaLingo Screenshot](docs/screenshot-pdf.png)

## 特徴

- **文字長制限なし**: 一般の翻訳ツールでは2000文字程度の制限がありますが、LocaLingoではそのような制限はありません。使用するLLMサーバーの制限に依存しますが、数万、数十万文字の翻訳も可能です。
- **ローカルでの動作**: インターネット接続が不要で、データのプライバシーを保護できます。すべての翻訳処理はローカル環境で行われます。
- **使いやすいUI**: 直感的なユーザーインターフェースを提供し、簡単に翻訳作業を行えます。
- **複数言語対応**: 英語、日本語、中国語、韓国語、フランス語、ドイツ語、スペイン語など、多数の言語間での翻訳が可能です。
- **PDF翻訳対応**: PDFファイルの翻訳が可能です。フォーマットを維持したまま翻訳を行います。

## 動作させる手順

### LLMサーバーの用意

1. LM StudioやOllamaなど、OpenAI互換APIを持ったローカルLLMサーバーをインストールし、起動します。
2. [pfnet/plamo-2-translate · Hugging Face](https://huggingface.co/pfnet/plamo-2-translate)や[mmnga/plamo-2-translate-gguf · Hugging Face](https://huggingface.co/mmnga/plamo-2-translate-gguf)などを参考に、PLaMo翻訳モデルをLLMサーバーにロードします。
3. LLMサーバーがOpenAI互換APIで動作していることを確認します。
   - 例えばLM Studioの場合、Serve on Local Networkのオプションを有効にする必要があります。

以下のようなcurlコマンドを実行して、LLMサーバーが正しく動作していることを確認します。ポート番号やエンドポイントは、使用しているLLMサーバーに応じて適宜変更してください。

```bash
curl http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "plamo-2-translate",
    "messages": [
      {
        "role": "user",
        "content": "<|plamo:op|>dataset\ntranslation\n\n<|plamo:op|>input lang=English\nHello!\n<|plamo:op|>output lang=Japanese"
      }
    ],
    "stop": ["<|plamo:op|>", "<|plamo:reserved:0x1E|>"]
  }'
```

PLaMo翻訳モデルは長文翻訳に対応していますが、ほとんどの場合LLMサーバーの設定で出力トークン長が制限されています。出力トークン長の設定を適切に調整してください。

### ローカルでのみ動作させる場合

1. compose.ymlを開き、tunnelに関するセクションをコメントアウトあるいは削除します。また、`LLM_ENDPOINT`環境変数を、使用しているLLMサーバーのエンドポイントに設定します。
2. 以下のコマンドを実行して、LocaLingoを起動します。

```bash
sudo docker-compose up -d
```

### FastAPI テキスト翻訳 UI

FastAPI サービスは、TranslatorUI のテキスト翻訳 UI と API をポート 4568 で配信します。
リポジトリー直下に `.env.template` をコピーして `.env` を作成し、LM Studio が公開している実際の
モデル ID と接続先を設定してください。`LLM_ENDPOINT` は `/v1` を含めないルート URL です。

macOS / Linux / WSL では、リポジトリー直下から次のラッパーを実行してください。
既存の `.venv` を利用し、存在しない場合は Python 3.12 以上（より新しい版を含む）で作成し、
不足している依存関係を導入してから API を起動します。仮想環境の有効化は不要です。

```bash
./start-translator-ui.sh
```

Windows PowerShell では、同じ命名規則の PowerShell ラッパーを使用します。

```powershell
.\start-translator-ui.ps1
```

既定ではローカル専用の `127.0.0.1:4568` で起動します。外部から到達可能にする場合や、別ポートを
使う場合は引数を指定します。WSL を含む macOS / Linux では次のように指定します。

```bash
./start-translator-ui.sh --listen-host 0.0.0.0 --port 4568
```

PowerShell では次のように指定します。

```powershell
.\start-translator-ui.ps1 -ListenHost 0.0.0.0 -Port 4568
```

依存関係を明示的に更新するには、Bash では `--install-dependencies`、PowerShell では
`-InstallDependencies` を指定します。仮想環境を作り直すには、Bash では `--recreate-venv`、
PowerShell では `-RecreateVenv` を指定します。`.env` がない場合は、ラッパーが `.env.template` を基に
ホスト直接実行用の `LLM_ENDPOINT=http://localhost:1234` を設定した `.env` を作成します。
作成後は LM Studio が公開している実際のモデル ID を確認してください。

`LLM_MODEL_ENDPOINT` と `LLM_CHAT_ENDPOINT` は、モデル一覧と Chat Completions の API パスを
個別に指定します。標準的な OpenAI 互換サーバーでは既定値の `/v1/models` と
`/v1/chat/completions` を使います。ベースURLからの絶対パスのほか、`https://...` の完全URLも
設定できるため、非標準のパス・別ホストにある OpenAI 互換エンドポイントにも対応できます。

起動後は、macOS / Linux / WSL では別の端末から次のヘルスチェックを実行できます。

```bash
curl http://localhost:4568/health
```

PowerShell では次を実行します。

```powershell
Invoke-RestMethod http://localhost:4568/health
```

`{"status":"ok"}` が返れば、Python API は起動しています。ブラウザーで
`http://localhost:4568/` を開くと FastAPI が配信する UI を使用できます。テキスト翻訳は同一
オリジンの `/api/translate-text` を呼び出し、SSE で結果を順次表示します。

この段階では `SAVE_TRANSLATIONS=false` のままにしてください。Ruby と Python が同じ
`localingo/data/translations.json` を同時に更新しないためです。Python UI は明示的な言語ペアのみ
対応しており、`auto` と `ja-easy` は使用できません。PDF 翻訳は Python 側への移行中のため、
FastAPI 配信 UI では現在利用できません。移行期間中、ポート 4567 の Ruby アプリケーションは
レガシー UI / PDF 検証用としてのみ残ります。

### Cloudflare Tunnelを用いて外部公開する場合

Cloudflareのサービスについての詳細な説明は他のドキュメントを参照してください。

1. compose.ymlを開き、`LLM_ENDPOINT`環境変数を使用しているLLMサーバーのエンドポイントに設定します。
2. `.env`ファイルを作成し、Cloudflare Tunnelの認証トークンを`TUNNEL_TOKEN`環境変数に設定します。
3. 必要に応じてCloudflare Accessの設定を行って下さい。この設定を行わない場合、全世界の誰でも翻訳サービスにアクセスできるようになります。
4. 以下のコマンドを実行して、LocaLingoを起動します。

```bash
sudo docker-compose up -d
```

## 注意事項

1. LocaLingoは、Preferred Networksが開発したPLaMo翻訳モデルを利用しています。PLaMo翻訳モデルの使用には、PLaMoコミュニティライセンスに従う必要があります。具体的には、個人や中小規模の企業は有償無償問わず自由に使用できますが、大規模な商用利用には別途ライセンス契約が必要です。詳細は[PLaMo Community Licenseについて](https://tech.preferred.jp/ja/blog/plamo-community-license/)や[PLaMoコミュニティライセンス契約](https://plamo.preferredai.jp/info/plamo-community-license-ja)をご参照ください。
2. LocaLingoはLLMサーバーの機能を持っていません。動作させるためには、LM StudioやOllamaなどのOpenAI互換APIを持ったローカルLLMサーバーが必要です。
3. 初期状態ではすべての翻訳を記録します。翻訳データを保存しないようにするには、compose.yml内の`SAVE_TRANSLATIONS`環境変数を`false`に設定してください。
