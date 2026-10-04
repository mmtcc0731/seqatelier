"""マルチプルアライメント（A-10）のテスト。

Phase 1時点では`align_sequences`はスタブであり、実処理を行わない。
入力バリデーション（対応ツール名・配列数）と、ツール未検出時 / スタブ未実装時
のいずれでも明確な`AlignmentError`メッセージ（サイレントなImportErrorではない）
を返すことを検証する。
"""

from __future__ import annotations

import shutil

import pytest

from seqatelier.alignment.align import AlignmentError, align_sequences


def test_alignment_stub_message():
    sequences = {"seq1": "ACGTACGTACGT", "seq2": "ACGTACGTACGA"}

    with pytest.raises(AlignmentError) as excinfo:
        align_sequences(sequences, tool="mafft")

    message = str(excinfo.value)
    assert message  # 空でない、明確なメッセージであること

    if shutil.which("mafft") is None:
        assert "mafft" in message
        assert "見つかりません" in message
    else:
        assert "スタブ" in message


def test_alignment_unsupported_tool_raises():
    with pytest.raises(AlignmentError):
        align_sequences({"a": "ACGT", "b": "ACGT"}, tool="clustalo")


def test_alignment_too_few_sequences_raises():
    with pytest.raises(AlignmentError):
        align_sequences({"only_one": "ACGT"}, tool="mafft")
