"""SeqAtelier — ローカルファースト、実験者優先の配列管理・プライマー設計ツールキット。

Claude Codeから直接駆動されることを想定した、Benchlingの代替（Phase 1の
スコープは配列管理・プライマー設計・コドン最適化・線形マップ）:
GenBankファイルを読み込み、SeqAtelierの関数を呼び、結果を書き戻す。

サブパッケージ:

- `seqatelier.core`: GenBank I/O（`LabRecord`）、位置解決（`resolve_site`）、
  配列インデックス（`data/index.csv`）、共有の型・例外定義。
- `seqatelier.primer`: Tm計算、In-Fusion設計、QuikChange設計、primer_bind
  アノテーション、primer3ラッパー（オプション）。
- `seqatelier.codon`: CAI基準のコドン最適化と合成DNA発注時の問題検出。
- `seqatelier.display`: 線形テキストシーケンスマップ。
- `seqatelier.alignment`: 外部CLIアライメントツールのラッパー（スタブ）。

全ての公開関数の入出力は、BioPythonオブジェクト（設計関数の入力側）または
JSON安全なプリミティブであり、結果は必ずフラットな`to_dict()`を持つ
dataclassとして返す（`seqatelier.core.types`参照、WC-7: MCPサーバー化を見据えた
構造化I/O）。
"""

from __future__ import annotations

__version__ = "0.3.0"
