"""プライマーのprimer_bind featureへの書き戻し（A-12）のテスト。

`add_primer_feature`/`annotate_primer`/`annotate_primer_pair`経由で、設計済み
プライマーがGenBankのprimer_bind featureとして書き戻され、`/label`・`/note`
qualifierにプライマー名・用途・Tmが記録され、GenBank往復後も保持されることを
検証する。
"""

from __future__ import annotations

from seqatelier.core.sequence import LabRecord, parse_seqatelier_note
from seqatelier.core.types import Primer, PrimerPair, PurificationGrade, Strand
from seqatelier.primer.annotate import annotate_primer, annotate_primer_pair
from seqatelier.primer.infusion import design_infusion


def _make_primer(name: str, start: int, end: int, strand: Strand = 1) -> Primer:
    return Primer(
        name=name,
        sequence="ACGTACGTACGTACGTACGT",
        tm_celsius=60.2,
        gc_percent=50.0,
        purification=PurificationGrade.HPLC,
        binding_start=start,
        binding_end=end,
        strand=strand,
    )


def test_primer_feature_added(sample_vector_record):
    before = len(sample_vector_record.record.features)

    primer = _make_primer("test_primer", 10, 30)
    annotate_primer(sample_vector_record, primer, "test purpose")

    after = len(sample_vector_record.record.features)
    assert after == before + 1

    primer_binds = [f for f in sample_vector_record.features_typed if f.feature_type == "primer_bind"]
    assert len(primer_binds) == 1
    assert primer_binds[0].label == "test_primer"


def test_primer_note_contains_tm(sample_vector_record):
    primer = _make_primer("tm_test_primer", 40, 70)
    annotate_primer(sample_vector_record, primer, "tm check")

    primer_bind = next(
        f for f in sample_vector_record.features_typed if f.feature_type == "primer_bind"
    )
    note = primer_bind.qualifiers["note"][0]
    assert note.startswith("seqatelier:")

    parsed_note = parse_seqatelier_note(note)
    assert parsed_note["tm"] == "60.2"
    assert parsed_note["purpose"] == "tm check"
    assert parsed_note["gc"] == "50.0"


def test_annotate_primer_pair_adds_both(sample_vector_record):
    forward = _make_primer("pair_f", 100, 120, strand=1)
    reverse = _make_primer("pair_r", 100, 120, strand=-1)
    pair = PrimerPair(forward=forward, reverse=reverse, product_size=20)

    before = len(sample_vector_record.record.features)
    annotate_primer_pair(sample_vector_record, pair, "pair test")
    after = len(sample_vector_record.record.features)

    assert after == before + 2
    primer_binds = [f for f in sample_vector_record.features_typed if f.feature_type == "primer_bind"]
    labels = {f.label for f in primer_binds}
    assert {"pair_f", "pair_r"} <= labels


def test_genbank_roundtrip_with_primers(sample_vector_record, sample_insert_record, tmp_path):
    design_infusion(
        sample_vector_record, sample_insert_record, insertion_site="GFP", construct_name="roundtrip_test"
    )

    out_path = tmp_path / "vector_with_primers.gb"
    sample_vector_record.to_genbank(out_path)
    reloaded = LabRecord.from_genbank(out_path)

    primer_binds = [f for f in reloaded.features_typed if f.feature_type == "primer_bind"]
    # ベクター線状化F/Rの2本（インサート増幅プライマーは相同領域を含むキメラ配列で
    # 鋳型上に単一の連続結合部位を持たないため、binding_start/endが無くannotateされない）
    assert len(primer_binds) == 2

    for primer_bind in primer_binds:
        note = primer_bind.qualifiers["note"][0]
        parsed_note = parse_seqatelier_note(note)
        assert "purpose" in parsed_note
        assert "tm" in parsed_note
        assert "roundtrip_test" in parsed_note["purpose"]
