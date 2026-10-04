# 保存先と同期フォルダ

SeqAtelierはローカルのフォルダをworkspaceとして扱います。Dropbox、OneDrive、iCloud Driveなどは、
OS上で読み書きできる実体のあるフォルダとして提供される場合に指定できます。
各サービスのAPI接続・ログイン・同期処理はSeqAtelierには含めません。

## 端末ごとの設定

1. 最初の端末で `seqatelier --workspace "PATH" init` を実行する。
2. `seqatelier workspace use "PATH"` でその端末の保存先を登録する。
3. 別の端末ではフォルダ全体の同期・ダウンロードを待ち、その端末上のパスで `workspace use` を実行する。
4. `seqatelier workspace show` で保存先と `workspace_id` を確認する。同じデータならIDも同じになる。

macOSのDropboxは環境によって `~/Library/CloudStorage/` 配下などに置かれます。
固定のフォルダ名を想定せず、実際に表示される保存先を指定してください。
WSLの `/mnt/c/...` とWindowsの `C:\...` も異なる登録です。同じworkspaceを両方から同時に編集しません。

設定はworkspaceの外側に保存されます。

| OS | 登録先 |
| --- | --- |
| Windows | `%LOCALAPPDATA%/seqatelier/config/config.json` |
| macOS | `~/Library/Application Support/seqatelier/config.json` |
| Linux | `$XDG_CONFIG_HOME/seqatelier/config.json`。未指定なら `~/.config/seqatelier/config.json` |

`SEQATELIER_CONFIG` で設定ファイルの場所を変更できます。設定ファイルと一時ロックの場所は同期させず、
各端末固有のままにします。ロックはOSのキャッシュディレクトリ、または `SEQATELIER_CACHE_HOME` の下に作ります。
同じworkspaceを扱うプロセスは同じユーザー・同じロックディレクトリを使ってください。
Composeの複数コンテナではロック用のvolumeも共有しています。

登録済みのフォルダが消えても別の空フォルダを自動生成しません。移動後は新しいパスを登録します。
`--workspace` と `SEQATELIER_WORKSPACE` は登録内容より優先されるため、通常は設定しなくて構いません。

## 編集と端末の切り替え

- workspace全体を「オフラインで利用可能」にし、配列ファイルのダウンロードを終えてから開く。
- 編集する端末は一度に一台。終了時はWeb/MCPサーバーも停止し、同期アプリで完了を確認する。
- 次の端末でも受信の完了を確認してから開く。ネットワークから切り離した複数端末で並行編集しない。
- アップグレード後は全端末で同じSeqAtelierの版を使う。

workspace内には次を保存します。

| ファイル | 内容 |
| --- | --- |
| `seqatelier.sqlite3` | レコード一覧、下書き・履歴、設計結果、workspaceの固有ID |
| `objects/<SHA256>.gb` | 各配列の変更しないGenBank版。参照は相対位置 |

0.3からSQLite処理はメモリ上で完了させ、完成したカタログ全体を一時ファイルから置き換えます。
同期フォルダ内のSQLiteを開いたまま更新せず、WALやjournalファイルも作りません。
同じ端末のCLI/Web/MCP間はロックと版チェックで調整します。処理中に外部から届いたカタログの変更も、
書き出し直前の比較で検出した場合は保存を中止します。

これは同期保証や端末間のロックではありません。カタログと配列が届く順番、複数端末の同時保存、
同期ソフトの競合コピーは制御できません。保存前の比較直後に外部更新が起こる競合も防ぎきれません。
カタログ全体をメモリへ読み書きするため、大量データの共同編集用データベースは想定していません。

## 同期途中・競合が起きたら

配列ファイル不足時はダウンロード完了を案内して保存を止めます。
`seqatelier*.sqlite3` に一致する別カタログがある場合も書き込みを止めます。
この検出ですべての同期サービス・言語・命名方式の競合を検出できるわけではありません。
競合が疑われる場合は各コピーを別々に保管し、同期を落ち着かせてから残す内容を確認してください。
競合コピーを自動削除・統合する機能はありません。

`-journal` / `-wal` / `-shm` が見つかる場合は旧アプリを終了し、同期状態を確認します。
必要な情報が残っている可能性があるので、これらを削除してエラーを回避しません。
元のアプリで整合するバックアップを作るか、以前のバックアップから復元してください。

## バックアップと旧開発版

`seqatelier backup OUTSIDE_WORKSPACE.zip` は、その時点の整合したカタログと全GenBank版を保存します。
ZIPは上書きせず、workspaceの外へ作ります。復元先は新しい空のフォルダです。
バックアップも同じworkspace IDを持つので、元データとコピーを同時に編集しないでください。

0.2の開発版で作ったworkspaceは、旧版の `backup` でまず保存し、全プロセスを終了してください。
0.3で `seqatelier --workspace PATH init` を実行すると履歴を保持してschema 2へ更新します。
更新したデータを旧版で開くことはできません。読み込みだけでは自動更新しません。

参考: [SQLiteのコピーと破損](https://sqlite.org/howtocorrupt.html)、
[Dropboxの競合コピー](https://help.dropbox.com/organize/conflicted-copy)、
[オフラインでの利用](https://help.dropbox.com/sync/make-files-online-only)。
