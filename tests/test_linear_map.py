"""線形テキストマップ（A-11）のテスト。

`render_linear_map`が、feature（promoter/CDS/rep_origin）をラベル付きで
表示し、CDSの下段に翻訳アミノ酸配列を併記すること、全長表示・指定領域表示の
両方が動作することを検証する。
"""

from __future__ import annotations

import json

from Bio.Seq import Seq

from seqatelier.display.linear_map import render_linear_map, render_linear_map_text


def test_full_map(sample_vector_record):
    linear_map = render_linear_map(sample_vector_record)

    assert linear_map.length == sample_vector_record.length
    assert linear_map.region_start == 1
    assert linear_map.region_end == sample_vector_record.length
    assert len(linear_map.lines) > 0

    bars_text = "\n".join(bar for line in linear_map.lines for bar in line.feature_bars)
    assert "lac" in bars_text
    assert "GFP" in bars_text
    assert "ampR" in bars_text
    assert "ori" in bars_text


def test_region_map(sample_vector_record):
    promoter = sample_vector_record.find_feature("lac")
    region = (promoter.location.start + 1, promoter.location.end)  # 1-based inclusive

    linear_map = render_linear_map(sample_vector_record, region=region)

    assert linear_map.region_start == region[0]
    assert linear_map.region_end == region[1]

    expected_seq = sample_vector_record.region(promoter.location.start, promoter.location.end)
    rendered = "".join(line.sequence_line for line in linear_map.lines).replace(" ", "")
    assert expected_seq in rendered


def test_cds_translation(sample_vector_record):
    ampr = sample_vector_record.find_feature("ampR", feature_type="CDS")
    region = (ampr.location.start + 1, ampr.location.end)

    linear_map = render_linear_map(sample_vector_record, region=region, show_translation=True)

    expected_protein = str(
        Seq(sample_vector_record.region(ampr.location.start, ampr.location.end)).translate(
            table="Standard"
        )
    )

    # feature/向きのバー行（'>'/'<'を含む）を除いた、翻訳アミノ酸配列の行だけを集める
    aa_lines = [
        bar for line in linear_map.lines for bar in line.feature_bars if ">" not in bar and "<" not in bar
    ]
    combined_aa_text = "".join(aa_lines)
    assert combined_aa_text.strip()  # 翻訳行が実際に生成されていること
    assert any(aa in combined_aa_text for aa in expected_protein[:10])


def test_json_serializable(sample_vector_record):
    linear_map = render_linear_map(sample_vector_record)
    payload = json.dumps(linear_map.to_dict())
    assert isinstance(payload, str)
    reparsed = json.loads(payload)
    assert reparsed["record_name"] == sample_vector_record.name
    assert reparsed["is_circular"] is True


def test_render_text(sample_vector_record):
    text = render_linear_map_text(sample_vector_record)
    assert isinstance(text, str)
    assert sample_vector_record.name in text
    assert "bp" in text
    assert "circular" in text


def test_to_dict_contains_text(sample_vector_record):
    linear_map = render_linear_map(sample_vector_record)
    d = linear_map.to_dict()
    assert "text" in d
    assert isinstance(d["text"], str)
    assert sample_vector_record.name in d["text"]


def test_region_feature_cont_label(sample_vector_record):
    """表示範囲外から始まるfeatureに(cont.)ラベルが付くことを検証。"""
    gfp = sample_vector_record.find_feature("GFP", feature_type="CDS")
    mid = (gfp.location.start + gfp.location.end) // 2
    region = (mid + 1, gfp.location.end)

    linear_map = render_linear_map(sample_vector_record, region=region)
    all_bars = "\n".join(bar for line in linear_map.lines for bar in line.feature_bars)
    assert "(cont.)" in all_bars
