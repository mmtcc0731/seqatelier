# 検証記録 — 2026-10-04

対象はSeqAtelier 0.3.0開発版。実験データを使わず、人工配列で検証しました。

| 検証 | 結果 |
|---|---|
| Windows / Python 3.13.2 | pytest: 119 passed, 1 skipped |
| Ubuntu 22.04 (WSL) / Python 3.13.2 | pytest: 119 passed, 1 skipped |
| 任意依存 primer3 | 未インストールのため実ライブラリを使う1件をskip |
| Pythonの静的解析 | Ruff: 成功、Pyright: 0 errors / 0 warnings |
| Web画面 | TypeScript型チェック、Vite production build成功 |
| wheel単体 | 新しいWindows仮想環境へインストールし、ソース外からデモ初期化・doctor・Web/MCP import成功 |
| MCP stdio | 公式SDKクライアントから別プロセスへ接続し、ツール実行成功 |
| MCP Streamable HTTP | 初期化とツール実行、トークンなしの拒否を確認 |
| プラグイン設定 | plugin.json / mcp.jsonを公式JSON Schemaで検証済み |
| 同梱スキル | skill-creatorのquick_validate成功 |
| Docker Compose | configの構文・展開検証成功。実ビルド・起動は未検証 |
| ブラウザ操作 | 合成デモでfeature編集→下書き→確定保存→履歴表示を確認 |

データ保存・復元のテストは、同時書き込みの競合、再起動後の下書き、版の復元、バックアップの展開、
オブジェクト破損の検出、設計プレビューで元配列が変化しないこと、入力版の変化による保存拒否を含みます。
CDSの逆鎖・codon_start、CDS外の残基指定、結合部位のコドンも検証しました。

0.3では同一workspaceを異なるパスへコピーして利用するテスト、端末固有の設定とworkspace IDの照合、
保存先消失時の空データ作成拒否、メモリ上の処理失敗時にカタログを変更しないこと、別プロセスの書き込み、
同期途中の欠損・競合コピー・保存中の外部変更の検出、旧schemaの更新を追加しました。
Dropbox等の実サービスとの同期は実行していません。

配布wheelにWeb画面が含まれること、研究データ・SQLite DB・仮想環境・node_modules・旧protocolが
配布アーカイブに含まれないことを確認しています。

未確認: macOS実機、Dockerコンテナ実行、実際のCodexへの登録・ツール実行、ChatGPT Dots接続、
公開HTTPS/OAuth環境、GitHub Actions実行、公開レジストリへのアップロード。
MCP SDKでの通信確認を、これらの実製品・クラウド環境の検証済みとは扱っていません。
