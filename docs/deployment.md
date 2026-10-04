# 配布と他端末への導入

基本構成はGitHubからプログラムを配布し、利用する各コンピューターで実行する形です。
自前の同期フォルダへデータを置くため、SeqAtelier専用の常時稼働サーバーは契約しません。
GitHubの公開リポジトリとReleasesを使った配布にサーバー契約は不要です。
既存のDropboxやChatGPT/Codexの契約・容量・利用上限は、それぞれのサービスに従います。

## 配布物

- `seqatelier-0.3.0-py3-none-any.whl`: インストール用。Web画面を含むためNode.js不要。
- `seqatelier-0.3.0.tar.gz`: ソース配布。
- `SHA256SUMS.txt`: 配布ファイルのチェックサム。
- `plugin/`: ローカルMCP設定と配列設計用スキル。パッケージのインストールは別途必要。

公開先は [mmtcc0731/seqatelier](https://github.com/mmtcc0731/seqatelier) です。
配布ファイルは [Releases](https://github.com/mmtcc0731/seqatelier/releases) から入手します。
PyPI登録、公開済みプラグインストアへの登録は行っていません。
研究データ・workspace・ユーザーごとの保存先設定を配布物へ含めません。

## 利用するコンピューター

1. Python 3.13以上を用意し、専用の仮想環境にwheelをインストールする。
2. 初回だけデータフォルダを初期化し、その端末のパスを `workspace use` で登録する。
3. `seqatelier doctor` で版、保存先、Web/MCPの準備状況を確認する。
4. CLIを直接使うか、`seqatelier serve` でWebを開くか、MCP対応クライアントに `seqatelier mcp` を登録する。

別のコンピューターにはプログラムを別途インストールします。仮想環境を端末間でコピーしません。
データフォルダの同期とパス登録は [storage.md](storage.md)、具体的なコマンドは [README](../README.md) にあります。

## CodexとChatGPT Dots

Codex向けにはCLIとstdio MCPを用意しています。MCP SDKを使った通信を検証済みですが、
実際のCodexへの登録・利用確認は別途必要です。

Dotsにはクラウド用コンピューターとアプリ/プラグインの接続が用意されていますが、
この配布物をDotsへインストールして使う一連の操作はまだ検証していません。
Python実行環境とファイル保存先を使える場合はCLIを使う方針です。
DropboxのChatGPT接続だけでクラウド用コンピューターに同期フォルダがマウントされるとは想定しません。

同期フォルダが使えない実行環境では、バックアップZIPを作業ディレクトリへ展開して使えます。
この場合、更新したコピーと元のworkspaceの自動統合は行いません。利用を終えたコピーを保存し、
どちらを次に使うか確認して切り替えます。

常時アクセスできるHTTPS MCPが必要になった場合だけ、[hosting.md](hosting.md) のOAuth構成を検討します。
その構成には別途サーバー費用が発生し得ます。ローカル利用にはOAuth、Auth0、Render設定は不要です。

## 開発者向け公開手順

ソースだけをリポジトリへコミットし、CIでWindows/Linux/macOSのテストとwheelビルドを確認します。
Releases用workflowは手動実行し、テスト・画面ビルド・クリーンインストールの確認後に
`v0.3.0` の開発版リリースとwheel、sdist、チェックサムを公開します。
バージョンごとのリリースを上書きする運用はしません。実際に公開したURLとCI結果で完了を確認します。

[GitHubのプラン](https://docs.github.com/en/get-started/learning-about-github/githubs-plans) /
[Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) /
[Dotsのコンピューターとアプリ](https://learn.chatgpt.com/docs/dots/computers-and-apps)
