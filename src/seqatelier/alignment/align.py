"""マルチプルアライメント実行のスタブ（WC-6）。

MAFFT/MUSCLEをローカルCLIツールとして呼び出すラッパーを想定している。
Phase 1ではスタブとして、前提条件（配列数・ツール名・PATH上のツール有無）
を検証し、未実装の実行部分についても明確なエラーメッセージ（サイレントな
ImportErrorではない）を返す。**実際の呼び出し・FASTA入出力パース処理は
Phase 2で実装予定であり、`align_sequences`は現時点では常にエラーを送出する
（`seqatelier.alignment`の公開API（`__all__`）からも意図的に除外している）。**
"""

from __future__ import annotations

import shutil
from typing import Any

from seqatelier.core.types import SeqAtelierError

__all__ = ["AlignmentError", "align_sequences"]

_SUPPORTED_TOOLS = ("mafft", "muscle")


class AlignmentError(SeqAtelierError):
    """外部アライメントツール（MAFFT/MUSCLE）が利用できない、または失敗した場合に送出される。"""


def align_sequences(sequences: dict[str, str], tool: str = "mafft") -> dict[str, Any]:
    """複数配列アライメントを外部CLIツールで実行する（WC-6、現時点ではスタブ）。

    Parameters
    ----------
    sequences:
        `{配列名: 配列}`の辞書。2件以上必要。
    tool:
        `"mafft"`または`"muscle"`。

    Returns
    -------
    dict
        （将来実装時）`{"tool": str, "aligned": {name: aligned_sequence}, "command": list[str]}`。

    Raises
    ------
    AlignmentError
        `tool`が未対応、`sequences`が2件未満、ツールがPATH上に見つからない
        場合（インストール方法をメッセージに含める）、または
        （現時点では常に）実際の呼び出し・パース処理が未実装の場合。
    """
    if tool not in _SUPPORTED_TOOLS:
        raise AlignmentError(f"toolは{_SUPPORTED_TOOLS}のいずれかを指定してください（'{tool}'は不正です）。")
    if len(sequences) < 2:
        raise AlignmentError(
            f"アライメントには2件以上の配列が必要です（{len(sequences)}件が指定されました）。"
        )
    if shutil.which(tool) is None:
        raise AlignmentError(
            f"'{tool}'が見つかりません。PATH上にインストールされているか確認してください"
            f"（例: `conda install -c bioconda {tool}`、または`brew install {tool}`）。"
            "SeqAtelierはこの外部ツール自体を配布しません（WC-6は外部CLIのラッパーとして設計されています）。"
        )
    raise AlignmentError(
        f"align_sequences()は現時点でスタブです。'{tool}'はPATH上に検出されましたが、"
        "実際の呼び出し・FASTA入出力パース処理は未実装です（Phase 2で実装予定）。"
    )
