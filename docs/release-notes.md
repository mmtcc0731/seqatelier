SeqAtelier 0.3.0 開発版。GenBank管理、配列表示、プライマー設計をCLI・Web・MCPから使えます。

データ用フォルダはDropboxなどの同期フォルダを指定でき、端末ごとに `seqatelier workspace use PATH` で登録します。
一度に一台で編集し、同期完了後に別の端末へ切り替えてください。アプリ自身は同期・競合統合を保証しません。

Python 3.13以上で、wheelをダウンロードして専用環境へインストールします。

```console
python -m pip install "./seqatelier-0.3.0-py3-none-any.whl[viewer,mcp]"
seqatelier --workspace ./my-sequences init --demo
seqatelier workspace use ./my-sequences
seqatelier serve
```

Web画面を同梱しているため、wheel利用時はNode.js不要です。基本構成に専用サーバー契約は不要です。
配布物には人工デモのみを含み、元の研究データは含みません。

Dotsの実環境、Dropbox等の実同期サービス、公開OAuthサーバーでの検証は未完了です。
旧0.2開発版のデータを使う場合は先にバックアップを取り、0.3の `--workspace PATH init` で更新します。
