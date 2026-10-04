"""QuikChangeプライマー設計（A-05）のテスト。

指定位置への点変異（置換）・挿入・欠失それぞれに対して、相補的なプライマー
ペアが正しく設計されることと、残基番号指定による点変異体設計
（`design_point_mutation_by_codon`）が正しい変異コドンを組み込むことを検証する。
"""

from __future__ import annotations

import json

import pytest
from Bio.Seq import Seq

from seqatelier.core.types import CodonHost, MutationType, PrimerDesignError
from seqatelier.primer.infusion import reverse_complement
from seqatelier.primer.quikchange import (
    design_point_mutation_by_codon,
    design_quikchange,
    format_order_summary,
)


def test_substitution(sample_vector_record):
    """3bpの置換がMutationType.SUBSTITUTIONとして設計され、相補プライマーペアになること。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    start0 = ampr.location.start + 30
    original = sample_vector_record.sequence[start0 : start0 + 3]
    new_seq = str(Seq(original).complement())
    assert new_seq != original  # 変異になっていることを確認

    design = design_quikchange(
        sample_vector_record,
        site=(start0 + 1, start0 + 3),  # 1-based inclusive
        new_sequence=new_seq,
        construct_name="subtest",
    )

    assert design.mutation_type == MutationType.SUBSTITUTION
    fwd = design.primer_pair.forward.sequence
    rev = design.primer_pair.reverse.sequence
    assert fwd == reverse_complement(rev)
    assert new_seq in fwd


def test_insertion(sample_vector_record):
    """挿入部位（単一点）を指定した場合、MutationType.INSERTIONになること。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    insertion_point = ampr.location.start + 60  # int指定 = 挿入点（0-based）

    design = design_quikchange(
        sample_vector_record,
        site=insertion_point,
        new_sequence="ATCG",
        construct_name="instest",
    )

    assert design.mutation_type == MutationType.INSERTION
    assert "ATCG" in design.primer_pair.forward.sequence


def test_deletion(sample_vector_record):
    """new_sequenceを空文字列にすると、MutationType.DELETIONになること。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    start0 = ampr.location.start + 90

    design = design_quikchange(
        sample_vector_record,
        site=(start0 + 1, start0 + 6),
        new_sequence="",
        construct_name="deltest",
    )

    assert design.mutation_type == MutationType.DELETION
    deleted_fragment = sample_vector_record.sequence[start0 : start0 + 6]
    assert deleted_fragment not in design.primer_pair.forward.sequence


def test_point_mutation_by_codon(sample_vector_record):
    """残基番号指定（design_point_mutation_by_codon）で正しい変異コドンが組み込まれること。"""
    residue_number = 10
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    codon_start = ampr.location.start + (residue_number - 1) * 3
    original_codon = sample_vector_record.sequence[codon_start : codon_start + 3]
    original_aa = str(Seq(original_codon).translate(table="Standard"))
    new_aa = "R" if original_aa != "R" else "K"

    design = design_point_mutation_by_codon(
        sample_vector_record,
        residue_number=residue_number,
        new_amino_acid=new_aa,
        host=CodonHost.ECOLI_K12,
        cds_feature_label="ampR",
    )

    assert design.mutation_type == MutationType.SUBSTITUTION
    assert f"残基{residue_number} {original_aa}→{new_aa}" in design.mutation_description

    # best_codon(new_aa, ECOLI_K12)が実際にプライマー配列へ組み込まれていること
    from seqatelier.codon.optimize import best_codon

    new_codon = best_codon(new_aa, CodonHost.ECOLI_K12)
    assert new_codon in design.primer_pair.forward.sequence


def test_point_mutation_by_codon_invalid_residue_raises(sample_vector_record):
    """residue_number < 1 や不正なアミノ酸コードはPrimerDesignErrorになること。"""
    with pytest.raises(PrimerDesignError):
        design_point_mutation_by_codon(
            sample_vector_record,
            residue_number=0,
            new_amino_acid="R",
            cds_feature_label="ampR",
        )
    with pytest.raises(PrimerDesignError):
        design_point_mutation_by_codon(
            sample_vector_record,
            residue_number=10,
            new_amino_acid="XX",
            cds_feature_label="ampR",
        )


def test_quikchange_complementary(sample_vector_record):
    """forwardプライマーが常にreverseプライマーの逆相補鎖と一致すること（古典的QuikChange設計）。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    insertion_point = ampr.location.start + 120

    design = design_quikchange(
        sample_vector_record,
        site=insertion_point,
        new_sequence="GGGCCC",
        construct_name="compltest",
    )

    fwd = design.primer_pair.forward.sequence
    rev = design.primer_pair.reverse.sequence
    assert fwd == reverse_complement(rev)
    assert rev == reverse_complement(fwd)


def test_quikchange_json_serializable(sample_vector_record):
    """`QuikChangeDesign.to_dict()`がJSONシリアライズ可能であること。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    start0 = ampr.location.start + 30
    original = sample_vector_record.sequence[start0 : start0 + 3]
    new_seq = str(Seq(original).complement())

    design = design_quikchange(
        sample_vector_record,
        site=(start0 + 1, start0 + 3),
        new_sequence=new_seq,
        construct_name="jsontest",
    )
    payload = json.dumps(design.to_dict())
    assert isinstance(payload, str)
    reparsed = json.loads(payload)
    assert reparsed["mutation_type"] == "substitution"


def test_quikchange_format_order_summary(sample_vector_record):
    """発注用Markdownサマリーが生成され、変異種別・プライマー名を含むこと。"""
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    start0 = ampr.location.start + 30
    original = sample_vector_record.sequence[start0 : start0 + 3]
    new_seq = str(Seq(original).complement())

    design = design_quikchange(
        sample_vector_record,
        site=(start0 + 1, start0 + 3),
        new_sequence=new_seq,
        construct_name="summarytest",
    )
    summary = format_order_summary(design)
    assert "QuikChange設計サマリー" in summary
    assert design.primer_pair.forward.name in summary
    assert design.primer_pair.reverse.name in summary
