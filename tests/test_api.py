"""Tests for seqatelier.api — file-path-based MCP boundary layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

from seqatelier.api import (
    infusion_from_files,
    linear_map_from_file,
    optimize_codons_api,
    point_mutation_from_file,
    quikchange_from_file,
    register_genbank,
    search_index,
)
from seqatelier.core.sequence import LabRecord


@pytest.fixture
def vector_gb(tmp_path: Path) -> str:
    seq = "ATGCGATCG" * 100 + "ATGGTGAGCAAGGGCGAGGAG" * 10 + "GCTAGCTAGC" * 50
    rec = SeqRecord(Seq(seq), id="pVec", name="pVec", description="test vector")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["topology"] = "circular"
    rec.features.append(
        SeqFeature(SimpleLocation(900, 1110), type="CDS", qualifiers={"label": ["GFP"]})
    )
    path = tmp_path / "vector.gb"
    lr = LabRecord(record=rec)
    lr.to_genbank(str(path))
    return str(path)


@pytest.fixture
def insert_gb(tmp_path: Path) -> str:
    seq = "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGG" * 8
    rec = SeqRecord(Seq(seq), id="mCherry", name="mCherry", description="insert")
    rec.annotations["molecule_type"] = "DNA"
    rec.annotations["topology"] = "linear"
    path = tmp_path / "insert.gb"
    lr = LabRecord(record=rec)
    lr.to_genbank(str(path))
    return str(path)


def test_infusion_from_files(vector_gb: str, insert_gb: str) -> None:
    result = infusion_from_files(vector_gb, insert_gb, insertion_site="GFP")
    assert isinstance(result, dict)
    assert "vector_linearization" in result
    assert "insert_amplification" in result
    json.dumps(result)


def test_infusion_with_list_site(vector_gb: str, insert_gb: str) -> None:
    result = infusion_from_files(vector_gb, insert_gb, insertion_site=[900, 1110])
    assert isinstance(result, dict)
    assert result["predicted_product_length"] > 0


def test_quikchange_from_file(vector_gb: str) -> None:
    result = quikchange_from_file(vector_gb, site=(950, 953), new_sequence="GCG")
    assert isinstance(result, dict)
    assert result["mutation_type"] in ("substitution", "insertion", "deletion")
    json.dumps(result)


def test_point_mutation_from_file(vector_gb: str) -> None:
    result = point_mutation_from_file(
        vector_gb, residue_number=5, new_amino_acid="A", cds_feature_label="GFP"
    )
    assert isinstance(result, dict)
    json.dumps(result)


def test_optimize_codons_api() -> None:
    result = optimize_codons_api("MKFLIV", "ecoli_k12")
    assert isinstance(result, dict)
    assert "optimized_dna_sequence" in result
    from Bio.Seq import Seq

    protein = str(Seq(result["optimized_dna_sequence"]).translate()).rstrip("*")
    assert protein == "MKFLIV"


def test_optimize_codons_host_alias() -> None:
    result = optimize_codons_api("MKF", "E. coli")
    assert result["host"] == "ecoli_k12"


def test_linear_map_from_file(vector_gb: str) -> None:
    result = linear_map_from_file(vector_gb, line_width=60)
    assert isinstance(result, dict)
    assert "text" in result or "lines" in result
    json.dumps(result)


def test_linear_map_with_region(vector_gb: str) -> None:
    result = linear_map_from_file(vector_gb, region_start=900, region_end=1000)
    assert isinstance(result, dict)


def test_search_index(tmp_path: Path, vector_gb: str) -> None:
    idx = str(tmp_path / "index.csv")
    register_genbank(idx, vector_gb, kind="plasmid", description="test vector")
    results = search_index(idx, "pVec")
    assert len(results) == 1
    assert results[0]["name"] == "pVec"


def test_register_genbank(tmp_path: Path, vector_gb: str) -> None:
    idx = str(tmp_path / "index.csv")
    entry = register_genbank(idx, vector_gb, kind="plasmid", tags="test,cloning")
    assert isinstance(entry, dict)
    assert entry["kind"] == "plasmid"
    json.dumps(entry)


def test_calc_tm_api() -> None:
    from seqatelier.api import calc_tm_api

    result = calc_tm_api("ATGCGATCGATCGATCGATCG")
    assert isinstance(result, dict)
    assert "tm_celsius" in result
    assert "gc_percent" in result
    assert "length" in result
    assert result["length"] == 21
    assert 50.0 < result["tm_celsius"] < 80.0
    json.dumps(result)


def test_normalize_site_bad_list() -> None:
    from seqatelier.api import _normalize_site
    from seqatelier.core.types import SequenceValidationError

    with pytest.raises(SequenceValidationError):
        _normalize_site([1, 2, 3])
