# SeqAtelier

GenBankの管理、プライマー設計、配列表示を、CLI・Web・MCPから使うためのパッケージです。
**SeqAtelier（シーク・アトリエ）** は、各コンピューターにインストールして使えます。
保存先にはDropboxなどの同期フォルダを指定できます。基本構成に専用サーバーや認証サービスの契約は不要です。
現在は0.3.0の開発版です。[GitHub](https://github.com/mmtcc0731/seqatelier) でソースを、
[Releases](https://github.com/mmtcc0731/seqatelier/releases) で配布ファイルを管理します。

## できること

- GenBankの取り込み・検索・書き出し、配列とfeatureの表示
- In-Fusion、QuikChange、CDS残基指定の変異プライマー設計、コドン最適化
- 設計のプレビューと保存、入力レコードの版の記録、発注用CSVの書き出し
- 編集履歴、下書きの復元、古い画面からの上書きを防ぐ版チェック
- 同じ処理をCLI・MCPから使用。Web画面は配布wheelに同梱

Python 3.13以上。wheelを使う場合はNode.js不要です。既存の研究データは含めていません。
デモは人工的に生成した短い配列です。

## 配布ファイルから試す

配布wheelと同じフォルダで、専用の仮想環境にインストールします。

```console
python -m venv .venv
# Windows PowerShell: .venv/Scripts/Activate.ps1
# macOS / Linux: source .venv/bin/activate
python -m pip install "./seqatelier-0.3.0-py3-none-any.whl[viewer,mcp]"
seqatelier --workspace ./my-sequences init --demo
seqatelier workspace use ./my-sequences
seqatelier doctor
seqatelier serve
```

ブラウザで http://127.0.0.1:8765 を開きます。「データ・接続」からGenBankの取り込み・
書き出し・履歴の復元ができます。取り込み元のファイルは変更しません。
画面の「保存」は確定版を更新します。編集中の下書きも復旧用に残ります。

`uv`を使う場合は、`uv tool install --python 3.13 "./seqatelier-0.3.0-py3-none-any.whl[viewer,mcp]"`
でもインストールできます。PyPIへの登録はまだ行っていません。

## Dropboxなどを保存先にする

プログラムを各端末へインストールし、**データ用フォルダだけ**を同期します。
例えばWindowsで、実際のDropboxフォルダ内に専用の保存先を作ります。
下のパスは例です。組織名・ユーザー名・同期サービスに合わせて置き換えてください。

```powershell
seqatelier --workspace "C:\Users\YOUR_NAME\Dropbox\SeqAtelier" init
seqatelier workspace use "C:\Users\YOUR_NAME\Dropbox\SeqAtelier"
seqatelier workspace show
```

別の端末では、同じフォルダの同期とダウンロードが終わってから、その端末のパスを登録します。
既存データを使う端末では `init` は不要です。

```console
seqatelier workspace use "/your/local/Dropbox/SeqAtelier"
seqatelier list
```

保存先の登録は端末ごとに記憶します。workspaceには絶対パスを保存せず、固有IDと相対位置でデータを管理します。
フォルダを移動した場合も `workspace use 新しいパス` で再登録できます。
登録済みの場所が見つからない場合や、別のworkspaceに置き換わっている場合はエラーにします。

運用は **一度に一台で編集し、アプリを終了して同期完了を待ってから別の端末へ移る** 形です。
フォルダ全体を「オフラインで利用可能」にしてください。同期や端末間の競合解決はDropbox等に任せます。
SeqAtelierは同期完了を保証せず、複数端末の変更を自動統合しません。
詳しくは [保存先と同期フォルダ](docs/storage.md) を参照してください。

保存先の優先順位は `--workspace PATH` → `SEQATELIER_WORKSPACE` → `workspace use` の登録 → OSの既定ディレクトリです。
プログラムや仮想環境は同期フォルダへ置く必要がありません。

```console
seqatelier import ./example.gb --id sample-001
seqatelier list sample
seqatelier show sample-001
seqatelier export sample-001 ./copy.gb
seqatelier backup ./backup-2026-10-04.zip
```

書き出しとバックアップは既存ファイルを上書きしません。
バックアップZIPを**新しい空のディレクトリ**に展開し、そのディレクトリを `--workspace` で指定すると復元できます。
workspaceは一人で使うことを想定しています。同期とは別にバックアップを残してください。

## Codexから使う

パッケージをインストールし、`workspace use` で保存先を登録した後、MCPを追加します。

```console
codex mcp add seqatelier -- seqatelier mcp
```

初期状態のMCPは読み取り・プレビュー専用です。新しいGenBankの取り込みと設計結果の保存も使う場合は、
最後に `--allow-writes` を加えます。既存配列の編集・削除をMCPへ公開することはしません。
GUIアプリから `seqatelier` が見つからない場合は、実行ファイルを絶対パスで指定してください。

同梱の `plugin/` はローカル開発用のプラグイン構成です。サーバー起動前にパッケージをインストールし、
workspaceを初期化してください。`plugin/mcp.json` のコマンドと環境変数を自分の環境に合わせられます。
`plugin/skills/sequence-design/SKILL.md` に設計時の座標・版の扱いをまとめています。

## ChatGPT Dots・別PCから使う

別PCも同じインストール手順です。Codex/Dotsが操作するコンピューターにPythonパッケージを入れ、
そのコンピューターから読めるworkspaceを指定してCLIを使う構成を基本にします。

Dotsのクラウド用コンピューターでの実行、ローカルMCP登録、Dropboxのフォルダとしての利用は未検証です。
**ChatGPTのDropbox接続を追加することと、実行環境に同期フォルダが現れることは別です。**
同期フォルダが使えない環境では、バックアップZIPを展開した作業用コピーを使えます。
元のworkspaceへ自動反映はしません。

GitHub公開・他端末への導入は [docs/deployment.md](docs/deployment.md) を参照してください。
任意のHTTPS/OAuthホスティングは [docs/hosting.md](docs/hosting.md) に分けています。

## 設計の再現性と座標

CLIの `design request.json` とMCPの `preview` は元配列を変更しません。
設計結果を保存すると、ソフトウェアの版、パラメーター、入力配列の版も一緒に残します。
発注CSVを作るだけで、業者への注文は行いません。

```json
{
  "method": "point_mutation",
  "name": "demo-A2R",
  "parameters": {
    "template_id": "demo-vector",
    "cds_feature_label": "demo_CDS",
    "residue_number": 2,
    "new_amino_acid": "R",
    "host": "human"
  }
}
```

```console
seqatelier --workspace ./my-sequences design request.json
```

保存する場合は、プレビューで得た `source_revisions` をリクエストの `expected_revisions` に加え、
`design request.json --save` を実行します。版が変わった場合は再プレビューが必要です。
保存結果の `id` を `seqatelier ... order ID primers.csv` へ渡すとCSVになります。

| 用途 | 座標 |
|---|---|
| 設計入力 `start_bp`, `end_bp` | 1-based、両端を含む |
| `insertion_after_bp` | 指定した塩基の直後。0は先頭より前 |
| CDSの `residue_number` | 1-based。逆鎖と `codon_start` を考慮 |
| Web APIとfeatureメタデータ | 0-based、終端を含まない |

結合したCDSの境界を跨ぐコドン置換や、宿主の標準コドン表と対応しない翻訳表は明示的に拒否します。
Web表示は結合featureを区間に分けて表示し、結合CDSのアミノ酸を単純な連続配列上に描画しません。
Tmとコドン最適化は計算上の提案です。実験の成否を検証したものではありません。

## ソースから開発・ビルド

Python 3.13以上、Node.js 22.12以上または24、npmを使います。

```console
uv sync --locked --extra dev --extra cloud
uv run python scripts/build_viewer.py
uv run pytest -q
uv run ruff check src tests scripts
uv run pyright
uv run python -m build
uv run python scripts/smoke_wheel.py
```

`scripts/build_viewer.py` がWeb画面をビルドしてwheelへ含めます。
`smoke_wheel.py` は新しい仮想環境にwheelをインストールし、ソースツリー外から初期化と起動準備を確認します。
`primer3` は別の任意依存です。必要なら `--extra primer3` を追加してください。

[変更内容](docs/changes.md) / [公開・配置](docs/deployment.md) / [MIT License](LICENSE)
