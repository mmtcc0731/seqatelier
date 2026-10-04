"""マルチプルアライメント実行のラッパー（WC-6、スタブ）。

`align_sequences`はPhase 2で実装予定の未完成スタブ（`seqatelier.alignment.align`
参照）であり、公開API（`__all__`）には含めない。動作を直接確認したい場合は
`from seqatelier.alignment.align import align_sequences`のようにサブモジュールを
明示的にimportすること。
"""

from __future__ import annotations

from seqatelier.alignment.align import AlignmentError

__all__ = ["AlignmentError"]
