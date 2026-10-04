"""SeqAtelierテストスイート共通fixture。

pUC19風の環状プラスミド（`sample_vector`）とmCherry CDS（`sample_insert`）を
決定論的な擬似乱数（固定シード）で生成する。実在のプラスミド配列を使わない
理由: 外部データファイルへの依存を避け、レポジトリ内で完結させるため
（生物学的な実在性は問わず、feature構造・ORFとしての妥当性のみを担保する）。

全fixtureはデフォルトのfunction scope（テストごとに新規生成）を明示的に使う。
`design_infusion`/`design_quikchange`はデフォルトで`annotate_*=True`となり、
渡された`LabRecord`へprimer_bind featureを書き戻す（副作用がある）ため、
テスト間でレコードを使い回すと直前のテストのアノテーションが残ってしまう。
そのため`sample_vector`/`sample_insert`はテストごとに独立した`SeqRecord`を
返し、それをラップする`sample_vector_record`/`sample_insert_record`も
自動的にテストごとに再生成される。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

from seqatelier.core.sequence import LabRecord


@pytest.fixture(autouse=True)
def isolated_local_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SEQATELIER_CONFIG", str(tmp_path / "local-settings" / "config.json"))
    monkeypatch.setenv("SEQATELIER_CACHE_HOME", str(tmp_path / "local-cache"))
    monkeypatch.delenv("SEQATELIER_WORKSPACE", raising=False)


# 64コドンから停止コドン（TAA/TAG/TGA）を除いた61個。テスト用ORFの中間部分に
# 停止コドンが紛れ込まないようにするために使う。
_SENSE_CODONS: list[str] = [
    "TTT", "TTC", "TTA", "TTG", "CTT", "CTC", "CTA", "CTG",
    "ATT", "ATC", "ATA", "ATG", "GTT", "GTC", "GTA", "GTG",
    "TCT", "TCC", "TCA", "TCG", "CCT", "CCC", "CCA", "CCG",
    "ACT", "ACC", "ACA", "ACG", "GCT", "GCC", "GCA", "GCG",
    "TAT", "TAC", "CAT", "CAC", "CAA", "CAG",
    "AAT", "AAC", "AAA", "AAG", "GAT", "GAC", "GAA", "GAG",
    "TGT", "TGC", "TGG", "CGT", "CGC", "CGA", "CGG",
    "AGT", "AGC", "AGA", "AGG", "GGT", "GGC", "GGA", "GGG",
]  # fmt: skip


def _random_dna(rng: random.Random, length: int) -> str:
    """`length`bpのランダムなACGT配列を返す（feature間の"埋め草"用）。"""
    return "".join(rng.choice("ACGT") for _ in range(length))


def _random_orf(rng: random.Random, codon_count: int, stop: str = "TAA") -> str:
    """ATGで始まり、途中に停止コドンを含まない長さ`3 + codon_count*3 + 3`のORFを返す。"""
    middle = "".join(rng.choice(_SENSE_CODONS) for _ in range(codon_count))
    return "ATG" + middle + stop


# pUC19風ベクター上のfeature位置（0-based half-open）。
# レイアウト: promoter(lac) [0,50) / 埋め草 / CDS(GFP) [500,1220) / 埋め草 /
#            CDS(ampR) [1400,2261) / 埋め草 / rep_origin(ori) [2400,2500) / 埋め草
# 合計2700bp。GFP・ampRはいずれも3の倍数長（ATG+中間コドン+終止コドン）。
_VECTOR_FEATURE_POSITIONS: dict[str, tuple[int, int]] = {
    "promoter": (0, 50),
    "gfp": (500, 1220),
    "ampr": (1400, 2261),
    "rep_origin": (2400, 2500),
}


def _build_vector_sequence() -> str:
    rng = random.Random(20260703)
    promoter = _random_dna(rng, 50)  # [0, 50)
    filler_1 = _random_dna(rng, 450)  # [50, 500)
    gfp_cds = _random_orf(rng, 238)  # [500, 1220) = 720bp
    filler_2 = _random_dna(rng, 180)  # [1220, 1400)
    ampr_cds = _random_orf(rng, 285)  # [1400, 2261) = 861bp
    filler_3 = _random_dna(rng, 139)  # [2261, 2400)
    rep_origin = _random_dna(rng, 100)  # [2400, 2500)
    filler_4 = _random_dna(rng, 200)  # [2500, 2700)
    return (
        promoter + filler_1 + gfp_cds + filler_2 + ampr_cds + filler_3 + rep_origin + filler_4
    )


@pytest.fixture
def tmp_index_path(tmp_path: Path) -> Path:
    """一時的な`index.csv`のパス。ファイル自体は最初の`add_entry`呼び出しで作られる。"""
    return tmp_path / "index.csv"


@pytest.fixture
def sample_vector() -> SeqRecord:
    """pUC19風の環状プラスミド（~2700bp）の生の`SeqRecord`。

    features: promoter(lac) / CDS(GFP, 500-1220) / CDS(ampR, 1400-2261) /
    rep_origin(ori, 2400-2500)。
    """
    sequence = _build_vector_sequence()
    record = SeqRecord(
        Seq(sequence), id="pTestVec", name="pTestVec", description="pUC19-like test vector"
    )
    record.annotations["molecule_type"] = "DNA"
    record.annotations["topology"] = "circular"

    promoter_start, promoter_end = _VECTOR_FEATURE_POSITIONS["promoter"]
    gfp_start, gfp_end = _VECTOR_FEATURE_POSITIONS["gfp"]
    ampr_start, ampr_end = _VECTOR_FEATURE_POSITIONS["ampr"]
    ori_start, ori_end = _VECTOR_FEATURE_POSITIONS["rep_origin"]

    record.features.append(
        SeqFeature(
            SimpleLocation(promoter_start, promoter_end, strand=1),
            type="promoter",
            qualifiers={"label": ["lac"], "gene": ["lac"]},
        )
    )
    record.features.append(
        SeqFeature(
            SimpleLocation(gfp_start, gfp_end, strand=1),
            type="CDS",
            qualifiers={
                "label": ["GFP"],
                "gene": ["GFP"],
                "product": ["green fluorescent protein"],
            },
        )
    )
    record.features.append(
        SeqFeature(
            SimpleLocation(ampr_start, ampr_end, strand=1),
            type="CDS",
            qualifiers={"label": ["ampR"], "gene": ["ampR"], "product": ["beta-lactamase"]},
        )
    )
    record.features.append(
        SeqFeature(
            SimpleLocation(ori_start, ori_end, strand=1),
            type="rep_origin",
            qualifiers={"label": ["ori"]},
        )
    )
    return record


@pytest.fixture
def sample_insert() -> SeqRecord:
    """mCherryのCDS（~720bp、線状）を表す生の`SeqRecord`。"""
    rng = random.Random(20260704)
    sequence = _random_orf(rng, 238)  # ATG + 238コドン + 終止 = 720bp
    record = SeqRecord(
        Seq(sequence), id="mCherry", name="mCherry", description="mCherry CDS (test fixture)"
    )
    record.annotations["molecule_type"] = "DNA"
    record.annotations["topology"] = "linear"
    record.features.append(
        SeqFeature(
            SimpleLocation(0, len(sequence), strand=1),
            type="CDS",
            qualifiers={
                "label": ["mCherry"],
                "gene": ["mCherry"],
                "product": ["mCherry fluorescent protein"],
            },
        )
    )
    return record


@pytest.fixture
def sample_vector_record(sample_vector: SeqRecord) -> LabRecord:
    """`sample_vector`をラップした`LabRecord`。プライマー設計関数はこちらを受け取る。"""
    return LabRecord(record=sample_vector)


@pytest.fixture
def sample_insert_record(sample_insert: SeqRecord) -> LabRecord:
    """`sample_insert`をラップした`LabRecord`。"""
    return LabRecord(record=sample_insert)
