"""In-Fusionプライマー設計（A-04）のテスト。

`seqatelier.primer.infusion.design_infusion`が、既知の（テスト用）プラスミドに
対して逆方向PCRベクター線状化プライマー + インサート増幅プライマーの4本を
正しく設計し、相同領域・Tm・産物長が仕様通りであることを検証する。
"""

from __future__ import annotations

import json

import pytest

from seqatelier.core.sequence import LabRecord
from seqatelier.core.types import PrimerDesignError
from seqatelier.primer.infusion import design_infusion, format_order_summary, reverse_complement


def test_basic_infusion_design(sample_vector_record, sample_insert_record):
    """GFPをmCherryに置換し、4本のプライマーがTm 55-72°Cの範囲に収まること。"""
    design = design_infusion(
        vector=sample_vector_record,
        insert=sample_insert_record,
        insertion_site="GFP",
        construct_name="GFP_to_mCherry",
    )
    primers = [
        design.vector_linearization.forward,
        design.vector_linearization.reverse,
        design.insert_amplification.forward,
        design.insert_amplification.reverse,
    ]
    assert len(primers) == 4
    for primer in primers:
        assert 55.0 <= primer.tm_celsius <= 72.0


def test_infusion_by_position(sample_vector_record, sample_insert_record):
    """挿入位置を(start, end)タプル（1-based inclusive）で指定できること。"""
    gfp = sample_vector_record.find_feature("GFP", feature_type="CDS")
    site = (gfp.location.start + 1, gfp.location.end)  # 1-based inclusive
    design = design_infusion(
        sample_vector_record, sample_insert_record, insertion_site=site, construct_name="by_pos"
    )
    assert design.insert_length == sample_insert_record.length


def test_infusion_by_feature_name(sample_vector_record, sample_insert_record):
    """挿入位置をfeatureラベル（文字列"GFP"）で指定できること。"""
    design = design_infusion(
        sample_vector_record, sample_insert_record, insertion_site="GFP", construct_name="by_name"
    )
    assert design.construct_name == "by_name"
    assert design.insert_length == sample_insert_record.length


def test_infusion_homology_arms(sample_vector_record, sample_insert_record):
    """インサートプライマーの5'側15bpがベクター側の接合部配列と一致すること。"""
    gfp = sample_vector_record.find_feature("GFP", feature_type="CDS")
    vector_seq = sample_vector_record.sequence

    design = design_infusion(
        sample_vector_record, sample_insert_record, insertion_site="GFP", construct_name="arms"
    )

    assert design.homology_arm_bp == 15
    fwd_tail = design.insert_amplification.forward.sequence[:15]
    rev_tail = design.insert_amplification.reverse.sequence[:15]

    expected_fwd_tail = vector_seq[gfp.location.start - 15 : gfp.location.start]
    expected_rev_tail = reverse_complement(vector_seq[gfp.location.end : gfp.location.end + 15])

    assert fwd_tail == expected_fwd_tail
    assert rev_tail == expected_rev_tail
    assert design.insert_amplification.forward.homology_arm_length == 15
    assert design.insert_amplification.reverse.homology_arm_length == 15


def test_infusion_product_length(sample_vector_record, sample_insert_record):
    """予測プロダクト長が「ベクター線状化産物長 + インサート長」と一致すること。"""
    gfp = sample_vector_record.find_feature("GFP", feature_type="CDS")
    deleted_length = gfp.location.end - gfp.location.start
    expected_vector_after = sample_vector_record.length - deleted_length
    expected_product = expected_vector_after + sample_insert_record.length

    design = design_infusion(
        sample_vector_record, sample_insert_record, insertion_site="GFP", construct_name="len_test"
    )

    assert design.vector_length_after == expected_vector_after
    assert design.predicted_product_length == expected_product


def test_infusion_linear_vector_raises(sample_vector, sample_insert_record):
    """ベクターが線状（linear）の場合、In-Fusion設計はPrimerDesignErrorを送出すること。"""
    sample_vector.annotations["topology"] = "linear"
    linear_vector_record = LabRecord(record=sample_vector)

    with pytest.raises(PrimerDesignError):
        design_infusion(linear_vector_record, sample_insert_record, insertion_site="GFP")


def test_infusion_json_serializable(sample_vector_record, sample_insert_record):
    """`InFusionDesign.to_dict()`がJSONシリアライズ可能であること（MCPツール化を見据えたWC-7）。"""
    design = design_infusion(
        sample_vector_record, sample_insert_record, insertion_site="GFP", construct_name="json_test"
    )
    payload = json.dumps(design.to_dict())
    assert isinstance(payload, str)
    reparsed = json.loads(payload)
    assert reparsed["construct_name"] == "json_test"
    assert reparsed["homology_arm_bp"] == 15


def test_infusion_format_order_summary(sample_vector_record, sample_insert_record):
    """発注用Markdown表が生成され、プライマー名と表の区切り記号を含むこと。"""
    design = design_infusion(
        sample_vector_record,
        sample_insert_record,
        insertion_site="GFP",
        construct_name="summary_test",
    )
    summary = format_order_summary(design)

    assert "In-Fusion設計サマリー" in summary
    assert "|" in summary
    assert design.vector_linearization.forward.name in summary
    assert design.vector_linearization.reverse.name in summary
    assert design.insert_amplification.forward.name in summary
    assert design.insert_amplification.reverse.name in summary


def test_tm_parameters_defaults():
    """TmParametersのデフォルト値が正しい合計濃度で設定されていることを検証（回帰防止）。"""
    from seqatelier.primer.tm import TmParameters

    default = TmParameters()
    assert default.dntp_mm == 0.8, "dNTPs must be total concentration (4x0.2 mM)"

    infusion = TmParameters.infusion_default()
    assert infusion.dntp_mm == 0.8
    assert infusion.mg_mm == 2.0

    qc = TmParameters.quikchange_default()
    assert qc.dntp_mm == 0.8
    assert qc.primer_conc_nm == 250.0

    pcr = TmParameters.pcr_default()
    assert pcr.dntp_mm == 0.8
