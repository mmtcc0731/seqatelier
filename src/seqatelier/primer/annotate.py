"""primer_bind featureのGenBank書き戻し用ユーティリティ（WC-10、設計C）。

主要な実装は`LabRecord.add_primer_feature`（`seqatelier.core.sequence`）にある。
このモジュールは、設計結果（`Primer`/`PrimerPair`）をまとめて書き戻すための
薄いバッチ用ラッパーを提供する（`design_infusion`/`design_quikchange`は
`annotate_vector`/`annotate_insert`/`annotate`引数経由で内部的に
`LabRecord.add_primer_feature`を直接呼ぶため、通常はそちらで十分——本モジュールは
設計関数を介さずに後から追加でアノテーションしたい場合向け）。
"""

from __future__ import annotations

from seqatelier.core.sequence import LabRecord
from seqatelier.core.types import Primer, PrimerPair

__all__ = ["annotate_primer", "annotate_primer_pair"]


def annotate_primer(record: LabRecord, primer: Primer, purpose: str) -> None:
    """`primer`を`record`にprimer_bind featureとして書き戻す。

    `primer.binding_start`/`binding_end`が未設定（例: In-Fusionインサート
    プライマーのように、単一の鋳型上の連続領域として表現できないキメラ
    プライマーの場合）の場合は何もしない（`LabRecord.add_primer_feature`の
    挙動に委ねる）。
    """
    record.add_primer_feature(primer, purpose)


def annotate_primer_pair(record: LabRecord, pair: PrimerPair, purpose: str) -> None:
    """`PrimerPair`の両方のプライマーをまとめて`record`に書き戻す。"""
    annotate_primer(record, pair.forward, f"{purpose} (forward)")
    annotate_primer(record, pair.reverse, f"{purpose} (reverse)")
