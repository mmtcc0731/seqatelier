"""コドン最適化（A-06）のテスト。

大腸菌・ヒト・Sf9（昆虫細胞）の3ホストに対し、`optimize_sequence`が
逆翻訳可能な（=同義置換のみを行った）DNA配列を出力すること、CAIが
妥当な範囲に収まること、ホストのエイリアス解決、合成上の問題検出、
カスタムホスト登録が機能することを検証する。
"""

from __future__ import annotations

import pytest
from Bio.Seq import Seq

from seqatelier.codon.optimize import (
    CODON_USAGE_TABLES,
    best_codon,
    detect_synthesis_issues,
    optimize_sequence,
    register_host_table,
    resolve_host,
)
from seqatelier.core.types import CodonHost, CodonOptimizationError

# 標準アミノ酸20種を1つずつ含むテスト配列（M・Wを含む、CAI計算では非判別扱い）。
_TEST_AA_SEQUENCE = "MAVLIPFWGSTCYNQDEHKR"


def _reverse_translate(dna_sequence: str) -> str:
    return str(Seq(dna_sequence).translate(table="Standard", to_stop=False))


def test_optimize_ecoli():
    result = optimize_sequence(_TEST_AA_SEQUENCE, host=CodonHost.ECOLI_K12)
    assert result.host == str(CodonHost.ECOLI_K12)
    assert _reverse_translate(result.optimized_dna_sequence) == _TEST_AA_SEQUENCE


def test_optimize_human():
    result = optimize_sequence(_TEST_AA_SEQUENCE, host=CodonHost.HUMAN)
    assert result.host == str(CodonHost.HUMAN)
    assert _reverse_translate(result.optimized_dna_sequence) == _TEST_AA_SEQUENCE


def test_optimize_sf9():
    result = optimize_sequence(_TEST_AA_SEQUENCE, host=CodonHost.SF9)
    assert result.host == str(CodonHost.SF9)
    assert _reverse_translate(result.optimized_dna_sequence) == _TEST_AA_SEQUENCE


@pytest.mark.parametrize("host", [CodonHost.ECOLI_K12, CodonHost.HUMAN, CodonHost.SF9])
def test_cai_range(host):
    result = optimize_sequence(_TEST_AA_SEQUENCE, host=host)
    assert result.cai is not None
    assert 0.0 < result.cai <= 1.0
    assert 0.0 <= result.gc_percent <= 100.0


def test_host_aliases():
    assert resolve_host("E. coli") == str(CodonHost.ECOLI_K12)
    assert resolve_host("e.coli") == str(CodonHost.ECOLI_K12)
    assert resolve_host("insect") == str(CodonHost.SF9)
    assert resolve_host("baculovirus") == str(CodonHost.SF9)
    assert resolve_host("human") == str(CodonHost.HUMAN)

    # エイリアス文字列を直接hostとして渡してもoptimize_sequenceが機能すること
    result = optimize_sequence(_TEST_AA_SEQUENCE, host="E. coli")
    assert result.host == str(CodonHost.ECOLI_K12)


def test_host_alias_unknown_raises():
    with pytest.raises(CodonOptimizationError):
        resolve_host("klingon")


def test_detect_synthesis_issues():
    # 塩基'A'が8連続するホモポリマー（デフォルト上限6を超える）を含む配列
    dna = "ATG" + "A" * 8 + "CCCGGGTTTAAACCCGGGTTTAAACCC" + "TAA"
    issues = detect_synthesis_issues(dna)
    kinds = {issue.kind for issue in issues}
    assert "homopolymer" in kinds
    homopolymer_issues = [i for i in issues if i.kind == "homopolymer"]
    assert any(i.severity == "warning" for i in homopolymer_issues)


def test_register_custom_host():
    custom_table = dict(CODON_USAGE_TABLES[str(CodonHost.HUMAN)])
    register_host_table("cho_custom", custom_table, aliases=["cho"])

    assert resolve_host("cho") == "cho_custom"
    assert resolve_host("cho_custom") == "cho_custom"

    result = optimize_sequence(_TEST_AA_SEQUENCE, host="cho_custom")
    assert _reverse_translate(result.optimized_dna_sequence) == _TEST_AA_SEQUENCE
    assert best_codon("R", "cho_custom") in CODON_USAGE_TABLES["cho_custom"]


def test_register_custom_host_rejects_incomplete_table():
    incomplete_table = {"ATG": 1.0}  # 64コドンを網羅していない
    with pytest.raises(CodonOptimizationError):
        register_host_table("broken_host", incomplete_table)
