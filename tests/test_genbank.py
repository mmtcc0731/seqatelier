"""GenBankファイルの読み書き（A-07）のテスト。

`LabRecord.to_genbank()` / `LabRecord.from_genbank()`の往復で、配列・feature
（type/location/qualifiers）・primer_bind の /note qualifier・環状/線状の
topologyが保持されることを検証する。
"""

from __future__ import annotations

from seqatelier.core.sequence import LabRecord, parse_seqatelier_note
from seqatelier.core.types import Primer, PurificationGrade


def test_read_write_roundtrip(sample_vector_record, tmp_path):
    out_path = tmp_path / "vector.gb"
    sample_vector_record.to_genbank(out_path)

    reloaded = LabRecord.from_genbank(out_path)

    assert reloaded.sequence == sample_vector_record.sequence
    assert reloaded.length == sample_vector_record.length


def test_features_preserved(sample_vector_record, tmp_path):
    out_path = tmp_path / "vector_features.gb"
    sample_vector_record.to_genbank(out_path)

    reloaded = LabRecord.from_genbank(out_path)

    original_locations = {
        (f.feature_type, f.location.start, f.location.end)
        for f in sample_vector_record.features_typed
    }
    reloaded_locations = {
        (f.feature_type, f.location.start, f.location.end) for f in reloaded.features_typed
    }
    assert original_locations == reloaded_locations

    ampr = reloaded.find_feature("ampR", feature_type="CDS")
    assert ampr is not None
    assert ampr.qualifiers["product"] == ["beta-lactamase"]

    promoter = reloaded.find_feature("lac")
    assert promoter is not None
    assert promoter.feature_type == "promoter"


def test_primer_bind_preserved(sample_vector_record, tmp_path):
    primer = Primer(
        name="test_primer",
        sequence="ACGTACGTACGTACGTACGT",
        tm_celsius=61.5,
        gc_percent=50.0,
        purification=PurificationGrade.HPLC,
        binding_start=10,
        binding_end=30,
        strand=1,
    )
    sample_vector_record.add_primer_feature(primer, "test purpose")

    out_path = tmp_path / "vector_primer.gb"
    sample_vector_record.to_genbank(out_path)
    reloaded = LabRecord.from_genbank(out_path)

    primer_binds = [f for f in reloaded.features_typed if f.feature_type == "primer_bind"]
    assert len(primer_binds) == 1
    assert primer_binds[0].qualifiers["label"] == ["test_primer"]

    note = primer_binds[0].qualifiers["note"][0]
    parsed_note = parse_seqatelier_note(note)
    assert parsed_note["purpose"] == "test purpose"
    assert parsed_note["tm"] == "61.5"
    assert parsed_note["gc"] == "50.0"


def test_from_sequence(tmp_path):
    record = LabRecord.from_sequence(
        "ATGGCTAGCTAA", name="minigene", description="test minimal gene", circular=False
    )
    out_path = tmp_path / "minigene.gb"
    record.to_genbank(out_path)

    reloaded = LabRecord.from_genbank(out_path)
    assert reloaded.sequence == "ATGGCTAGCTAA"
    assert reloaded.is_circular is False


def test_circular_topology(sample_vector_record, sample_insert_record, tmp_path):
    circular_path = tmp_path / "circular.gb"
    sample_vector_record.to_genbank(circular_path)
    reloaded_circular = LabRecord.from_genbank(circular_path)
    assert reloaded_circular.is_circular is True

    linear_path = tmp_path / "linear.gb"
    sample_insert_record.to_genbank(linear_path)
    reloaded_linear = LabRecord.from_genbank(linear_path)
    assert reloaded_linear.is_circular is False
