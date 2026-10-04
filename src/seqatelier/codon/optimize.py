"""CAI基準のコドン最適化と合成DNA発注時の問題検出（WC-3、設計C）。

タンパク質配列の各残基について、宿主の最頻用コドンを貪欲法で選びつつ、
以下の3つのソフト制約を（個別に緩和可能な優先順位で）考慮する:

1. 同一コドンの連続回数上限（`max_identical_codon_run`）。
2. 局所GC含量がスライディングウィンドウで`[gc_min, gc_max]`に収まること。
3. 指定した制限酵素認識配列を新たに作らないこと（`avoid_restriction_sites`）。

いずれも「絶対に守るべき制約」ではなく、Met/Trpの連続など、そもそも
同義コドンが1つしかなくどうやっても守れない場合があるため、後述の
段階的緩和（most-strict first）で必ずコドンを1つ選び、緩和した箇所は
`issues`に記録する。

宿主コドン使用頻度テーブル
--------------------------
同梱の3テーブル（ecoli_k12, human, sf9）は、公表されているコドン使用頻度
（Kazusa Codon Usage Database等）の傾向におおむね沿うよう手動でまとめた
近似値であり、特定データベースの完全な転記ではない。`register_host_table`
で読み込み時にBioPythonの標準遺伝暗号と突き合わせて自己検証する
（コドン→アミノ酸の対応にタイプミスがあれば、誤ったタンパク質を静かに
生成する代わりに、登録時点で明確に失敗する）。特定の公表テーブルへの
厳密な一致が必要な作業では、`register_host_table`で好みのソースから
読み込んだデータに差し替えること。
"""

from __future__ import annotations

import math
from functools import cache

from Bio.Seq import Seq
from Bio.SeqUtils import gc_fraction

from seqatelier.core.types import (
    CodonHost,
    CodonOptimizationError,
    CodonOptimizationIssue,
    CodonOptimizationResult,
)

__all__ = [
    "CODONS_BY_AMINO_ACID",
    "CODON_USAGE_TABLES",
    "DEFAULT_RESTRICTION_SITES",
    "GENETIC_CODE",
    "HOST_ALIASES",
    "best_codon",
    "calculate_cai",
    "detect_synthesis_issues",
    "optimize_sequence",
    "register_host_table",
    "resolve_host",
]

# --------------------------------------------------------------------------
# 標準遺伝暗号
# --------------------------------------------------------------------------

GENETIC_CODE: dict[str, str] = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

CODONS_BY_AMINO_ACID: dict[str, list[str]] = {}
for _codon, _aa in GENETIC_CODE.items():
    CODONS_BY_AMINO_ACID.setdefault(_aa, []).append(_codon)

_VALID_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
_NON_DISCRIMINATING_AA = frozenset("MW")  # 同義コドンが1つしかない(常にw=1)

# --------------------------------------------------------------------------
# 制限酵素認識配列（合成DNA発注時に避けたい代表的なもの）
# --------------------------------------------------------------------------

DEFAULT_RESTRICTION_SITES: dict[str, str] = {
    "EcoRI": "GAATTC",
    "BamHI": "GGATCC",
    "HindIII": "AAGCTT",
    "XhoI": "CTCGAG",
    "NotI": "GCGGCCGC",
    "NheI": "GCTAGC",
    "XbaI": "TCTAGA",
    "SalI": "GTCGAC",
    "NcoI": "CCATGG",
    "NdeI": "CATATG",
    "KpnI": "GGTACC",
    "SacI": "GAGCTC",
}

# --------------------------------------------------------------------------
# 宿主コドン使用頻度テーブル
# --------------------------------------------------------------------------
# アミノ酸ごとにグループ化した{codon: fraction}（各アミノ酸内の合計は約1.0）。
# 登録時にCODON_USAGE_TABLESへフラット化（{codon: fraction}、64コドン全て）
# して格納する。数値の出典については本モジュールのdocstringを参照。

_ECOLI_K12_NESTED: dict[str, dict[str, float]] = {
    "A": {"GCG": 0.36, "GCC": 0.27, "GCA": 0.21, "GCT": 0.16},
    "R": {"CGC": 0.40, "CGT": 0.38, "CGA": 0.06, "CGG": 0.07, "AGA": 0.07, "AGG": 0.02},
    "N": {"AAC": 0.55, "AAT": 0.45},
    "D": {"GAT": 0.63, "GAC": 0.37},
    "C": {"TGC": 0.55, "TGT": 0.45},
    "Q": {"CAG": 0.65, "CAA": 0.35},
    "E": {"GAA": 0.68, "GAG": 0.32},
    "G": {"GGC": 0.40, "GGT": 0.34, "GGG": 0.15, "GGA": 0.11},
    "H": {"CAT": 0.57, "CAC": 0.43},
    "I": {"ATT": 0.51, "ATC": 0.42, "ATA": 0.07},
    "L": {"CTG": 0.50, "TTA": 0.13, "TTG": 0.13, "CTT": 0.10, "CTC": 0.10, "CTA": 0.04},
    "K": {"AAA": 0.74, "AAG": 0.26},
    "M": {"ATG": 1.00},
    "F": {"TTT": 0.57, "TTC": 0.43},
    "P": {"CCG": 0.52, "CCA": 0.19, "CCT": 0.16, "CCC": 0.13},
    "S": {"AGC": 0.28, "TCT": 0.17, "TCC": 0.15, "AGT": 0.15, "TCA": 0.14, "TCG": 0.11},
    "T": {"ACC": 0.44, "ACG": 0.24, "ACT": 0.19, "ACA": 0.13},
    "W": {"TGG": 1.00},
    "Y": {"TAT": 0.57, "TAC": 0.43},
    "V": {"GTG": 0.37, "GTT": 0.28, "GTC": 0.20, "GTA": 0.15},
    "*": {"TAA": 0.61, "TGA": 0.30, "TAG": 0.09},
}

_HUMAN_NESTED: dict[str, dict[str, float]] = {
    "A": {"GCC": 0.40, "GCT": 0.27, "GCA": 0.23, "GCG": 0.10},
    "R": {"AGA": 0.21, "CGG": 0.20, "AGG": 0.20, "CGC": 0.18, "CGA": 0.11, "CGT": 0.10},
    "N": {"AAC": 0.53, "AAT": 0.47},
    "D": {"GAC": 0.54, "GAT": 0.46},
    "C": {"TGC": 0.55, "TGT": 0.45},
    "Q": {"CAG": 0.73, "CAA": 0.27},
    "E": {"GAG": 0.58, "GAA": 0.42},
    "G": {"GGC": 0.34, "GGA": 0.25, "GGG": 0.25, "GGT": 0.16},
    "H": {"CAC": 0.59, "CAT": 0.41},
    "I": {"ATC": 0.47, "ATT": 0.36, "ATA": 0.17},
    "L": {"CTG": 0.41, "CTC": 0.20, "CTT": 0.13, "TTG": 0.13, "TTA": 0.07, "CTA": 0.06},
    "K": {"AAG": 0.58, "AAA": 0.42},
    "M": {"ATG": 1.00},
    "F": {"TTC": 0.54, "TTT": 0.46},
    "P": {"CCC": 0.33, "CCT": 0.29, "CCA": 0.28, "CCG": 0.10},
    "S": {"AGC": 0.24, "TCC": 0.22, "TCT": 0.18, "AGT": 0.15, "TCA": 0.15, "TCG": 0.06},
    "T": {"ACC": 0.36, "ACA": 0.28, "ACT": 0.24, "ACG": 0.12},
    "W": {"TGG": 1.00},
    "Y": {"TAC": 0.56, "TAT": 0.44},
    "V": {"GTG": 0.47, "GTC": 0.24, "GTT": 0.18, "GTA": 0.11},
    "*": {"TGA": 0.47, "TAA": 0.28, "TAG": 0.25},
}

_SF9_NESTED: dict[str, dict[str, float]] = {
    "A": {"GCC": 0.34, "GCT": 0.30, "GCA": 0.24, "GCG": 0.12},
    "R": {"AGA": 0.28, "CGC": 0.16, "CGT": 0.16, "AGG": 0.16, "CGA": 0.14, "CGG": 0.10},
    "N": {"AAC": 0.55, "AAT": 0.45},
    "D": {"GAC": 0.53, "GAT": 0.47},
    "C": {"TGC": 0.52, "TGT": 0.48},
    "Q": {"CAG": 0.60, "CAA": 0.40},
    "E": {"GAG": 0.55, "GAA": 0.45},
    "G": {"GGA": 0.32, "GGC": 0.28, "GGT": 0.24, "GGG": 0.16},
    "H": {"CAC": 0.53, "CAT": 0.47},
    "I": {"ATC": 0.42, "ATT": 0.40, "ATA": 0.18},
    "L": {"CTG": 0.34, "TTG": 0.18, "CTC": 0.16, "TTA": 0.13, "CTT": 0.13, "CTA": 0.06},
    "K": {"AAG": 0.58, "AAA": 0.42},
    "M": {"ATG": 1.00},
    "F": {"TTC": 0.51, "TTT": 0.49},
    "P": {"CCA": 0.32, "CCC": 0.26, "CCT": 0.26, "CCG": 0.16},
    "S": {"AGC": 0.22, "TCC": 0.20, "TCT": 0.20, "AGT": 0.16, "TCA": 0.14, "TCG": 0.08},
    "T": {"ACC": 0.33, "ACA": 0.29, "ACT": 0.27, "ACG": 0.11},
    "W": {"TGG": 1.00},
    "Y": {"TAC": 0.52, "TAT": 0.48},
    "V": {"GTG": 0.38, "GTT": 0.24, "GTC": 0.22, "GTA": 0.16},
    "*": {"TAA": 0.42, "TGA": 0.32, "TAG": 0.26},
}


def _flatten(nested: dict[str, dict[str, float]]) -> dict[str, float]:
    flat: dict[str, float] = {}
    for codons in nested.values():
        flat.update(codons)
    return flat


_DEFAULT_ALIASES: dict[CodonHost, list[str]] = {
    CodonHost.ECOLI_K12: [
        "e. coli", "e.coli", "ecoli", "escherichia coli", "e coli", "k12", "bl21", "rosetta",
    ],
    CodonHost.HUMAN: ["human", "homo sapiens", "hsapiens", "hs"],
    CodonHost.SF9: [
        "insect", "sf9", "sf21", "spodoptera frugiperda", "baculovirus", "hi5",
    ],
}

CODON_USAGE_TABLES: dict[str, dict[str, float]] = {}
"""host識別子（`CodonHost`のstr値、または`register_host_table`で登録したカスタム名）
から、フラットな{codon: fraction}テーブル（64コドン全て）への辞書。"""

HOST_ALIASES: dict[str, str] = {}
"""小文字化したエイリアス文字列から、CODON_USAGE_TABLESのキーへの辞書。"""


# --------------------------------------------------------------------------
# 登録・検証
# --------------------------------------------------------------------------


def _validate_codon_table(name: str, table: dict[str, float]) -> None:
    missing = set(GENETIC_CODE) - set(table)
    extra = set(table) - set(GENETIC_CODE)
    if missing or extra:
        raise CodonOptimizationError(
            f"コドンテーブル'{name}'が64コドンを網羅していません"
            f"（不足: {sorted(missing)}、余分: {sorted(extra)}）。"
        )
    family_totals: dict[str, float] = {}
    for codon, freq in table.items():
        if freq < 0:
            raise CodonOptimizationError(f"コドンテーブル'{name}': {codon}の頻度が負です（{freq}）。")
        translated = str(Seq(codon).translate(table="Standard"))
        expected = GENETIC_CODE[codon]
        if translated != expected:
            raise CodonOptimizationError(
                f"コドンテーブル'{name}': {codon}はBioPythonの標準遺伝暗号で'{translated}'に"
                f"翻訳されますが、GENETIC_CODEでは'{expected}'として定義されています。"
                "テーブルが自己矛盾しています。"
            )
        family_totals[expected] = family_totals.get(expected, 0.0) + freq
    for aa, total in family_totals.items():
        if abs(total - 1.0) > 0.03:
            raise CodonOptimizationError(
                f"コドンテーブル'{name}': アミノ酸'{aa}'のコドン頻度合計が{total:.3f}です"
                "（1.0が期待値）。"
            )


def register_host_table(
    host: CodonHost | str,
    table: dict[str, float],
    aliases: list[str] | None = None,
) -> None:
    """宿主のコドン使用頻度テーブルを登録（または上書き）する。

    `table`は64コドン全てを網羅する{codon: fraction}（フラット）の辞書で、
    各アミノ酸内の頻度合計が約1.0である必要がある。各コドンが
    `GENETIC_CODE`と矛盾なく対応しているかをBioPythonの`Seq.translate`で
    検証する。これにより、SeqAtelierのソースを変更せずにカスタム宿主
    （CHO特化テーブル、植物テーブル、更新版Kazusaエクスポート等）を
    追加できる。

    Raises
    ------
    CodonOptimizationError
        `table`が上記のいずれかのチェックに失敗した場合。
    """
    host_key = str(host)
    _validate_codon_table(host_key, table)
    CODON_USAGE_TABLES[host_key] = dict(table)
    if aliases:
        for alias in aliases:
            HOST_ALIASES[alias.strip().lower()] = host_key
    _sorted_codons_for_aa.cache_clear()
    _relative_adaptiveness.cache_clear()


def resolve_host(host: CodonHost | str) -> str:
    """`host`（`CodonHost`メンバー・登録済みキー・エイリアス文字列）をテーブルキーに解決する。"""
    if isinstance(host, CodonHost):
        return str(host)
    key = host.strip()
    if key in CODON_USAGE_TABLES:
        return key
    alias_key = key.lower()
    if alias_key in HOST_ALIASES:
        return HOST_ALIASES[alias_key]
    raise CodonOptimizationError(
        f"ホスト'{host}'に対応するコドン使用頻度テーブルが登録されていません。"
        f"利用可能なホスト: {sorted(CODON_USAGE_TABLES)}。"
        f"利用可能なエイリアス: {sorted(HOST_ALIASES)}。"
        "register_host_table()でカスタムテーブルを登録できます。"
    )


@cache
def _sorted_codons_for_aa(host_key: str, aa: str) -> tuple[str, ...]:
    if host_key not in CODON_USAGE_TABLES:
        raise CodonOptimizationError(f"ホスト'{host_key}'は登録されていません。")
    table = CODON_USAGE_TABLES[host_key]
    codons = CODONS_BY_AMINO_ACID.get(aa)
    if not codons:
        raise CodonOptimizationError(f"アミノ酸'{aa}'に対応するコドンが見つかりません。")
    return tuple(sorted(codons, key=lambda c: table.get(c, 0.0), reverse=True))


_CAI_PSEUDOCOUNT = 1e-6
"""w_i=0（そのコドンの頻度が0、または未登録）となるコドンに与える下駄。

w=0のまま`math.log`に渡すと`ValueError`（またはCAI計算全体からの黙った
除外）になる。生物学的には「そのコドンはほぼ使われない」だけであり
「絶対に使われない」わけではないため、微小値で置き換えて対数を取れるように
し、かつCAIを正しく強く下げる（w=0を計算からこっそり除外すると、逆に
CAIが実態より高く出てしまう）。
"""


@cache
def _relative_adaptiveness(host_key: str) -> dict[str, float]:
    """Sharp & Li (1987)の相対適応度 w_i = freq(codon) / freq(そのアミノ酸の最頻コドン)。

    w_iが0になる場合（該当コドンの頻度が登録テーブル上0、またはテーブルに
    存在しない場合）は`_CAI_PSEUDOCOUNT`で置き換える。
    """
    table = CODON_USAGE_TABLES[host_key]
    family_max: dict[str, float] = {}
    for codon, aa in GENETIC_CODE.items():
        if aa == "*":
            continue
        family_max[aa] = max(family_max.get(aa, 0.0), table.get(codon, 0.0))
    weights: dict[str, float] = {}
    for codon, aa in GENETIC_CODE.items():
        if aa == "*":
            continue
        max_freq = family_max.get(aa, 0.0)
        raw_w = table.get(codon, 0.0) / max_freq if max_freq > 0 else 0.0
        weights[codon] = raw_w if raw_w > 0 else _CAI_PSEUDOCOUNT
    return weights


def best_codon(amino_acid: str, host: CodonHost | str) -> str:
    """`host`にとっての`amino_acid`の最頻コドンを返す。"""
    aa = amino_acid.strip().upper()
    if aa not in _VALID_AMINO_ACIDS:
        raise CodonOptimizationError(f"'{amino_acid}'は標準アミノ酸1文字コードではありません。")
    host_key = resolve_host(host)
    return _sorted_codons_for_aa(host_key, aa)[0]


def calculate_cai(dna_sequence: str, host: CodonHost | str) -> float | None:
    """`dna_sequence`の`host`に対するCodon Adaptation Index（Sharp & Li, 1987）を計算する。

    Met/Trp/stopコドン（常にw=1で判別に寄与しない）は除外する。判別に使える
    コドンが1つも無い場合（Met/Trpのみからなる極短ペプチド等）は`None`を返す。
    そのアミノ酸家系内で頻度0のコドン（宿主テーブル上ほぼ使われないコドン）は
    `_relative_adaptiveness`が`_CAI_PSEUDOCOUNT`を与えるため、計算から
    黙って除外されることはなく、CAIを正しく押し下げる。

    Raises
    ------
    CodonOptimizationError
        `host`が未登録、または配列長が3の倍数でない場合。
    """
    host_key = resolve_host(host)
    seq = dna_sequence.strip().upper()
    if not seq or len(seq) % 3 != 0:
        raise CodonOptimizationError(
            f"CAI計算にはDNA配列の長さが3の倍数である必要があります（{len(seq)}nt）。"
        )
    weights = _relative_adaptiveness(host_key)
    values = []
    for i in range(0, len(seq), 3):
        codon = seq[i : i + 3]
        aa = GENETIC_CODE.get(codon)
        if aa is None or aa == "*" or aa in _NON_DISCRIMINATING_AA:
            continue
        # weightsは_relative_adaptivenessでpseudocount済みのため常に>0。
        values.append(weights.get(codon, _CAI_PSEUDOCOUNT))
    if not values:
        return None
    log_mean = sum(math.log(v) for v in values) / len(values)
    return round(math.exp(log_mean), 4)


# --------------------------------------------------------------------------
# コドン選択（段階的制約緩和）
# --------------------------------------------------------------------------

_MIN_GC_SAMPLE = 12  # bp; これ未満の断片でのGC%判定はノイズが大きすぎる


def _tail_bases(codons: list[str], new_codon: str, window: int) -> str:
    needed_codons = window // 3 + 2
    combined = "".join((*codons[-needed_codons:], new_codon))
    return combined[-window:] if len(combined) >= window else combined


def _gc_window_ok(codons: list[str], new_codon: str, gc_min: float, gc_max: float, window: int) -> bool:
    tail = _tail_bases(codons, new_codon, window)
    if len(tail) < min(window, _MIN_GC_SAMPLE):
        return True
    return gc_min <= gc_fraction(tail) * 100.0 <= gc_max


def _introduces_site(
    codons: list[str], new_codon: str, sites: dict[str, str], *, check_window: int = 30
) -> bool:
    tail = _tail_bases(codons, new_codon, check_window)
    for site_seq in sites.values():
        rc = str(Seq(site_seq).reverse_complement())
        if site_seq in tail or rc in tail:
            return True
    return False


_RELAXATION_STAGES: tuple[tuple[str, ...], ...] = (
    ("run", "gc", "site"),
    ("gc", "site"),
    ("site",),
    (),
)


def _choose_codon(
    candidates: tuple[str, ...],
    *,
    codons: list[str],
    last_codon: str | None,
    run_length: int,
    max_run: int,
    gc_min: float,
    gc_max: float,
    gc_window: int,
    sites: dict[str, str],
) -> tuple[str, list[str]]:
    for stage in _RELAXATION_STAGES:
        for codon in candidates:
            if "run" in stage and codon == last_codon and run_length + 1 > max_run:
                continue
            if "gc" in stage and not _gc_window_ok(codons, codon, gc_min, gc_max, gc_window):
                continue
            if "site" in stage and sites and _introduces_site(codons, codon, sites):
                continue
            relaxed = [c for c in ("run", "gc", "site") if c not in stage]
            return codon, relaxed
    raise CodonOptimizationError("内部エラー: コドン候補が見つかりません。")  # pragma: no cover


def _compute_gc_windows(dna: str, window: int) -> list[float]:
    if window <= 0 or window > len(dna):
        return [round(gc_fraction(dna) * 100.0, 1)] if dna else []
    result = []
    for i in range(0, len(dna), window):
        chunk = dna[i : i + window]
        if len(chunk) < 3:
            continue
        result.append(round(gc_fraction(chunk) * 100.0, 1))
    return result


# --------------------------------------------------------------------------
# 公開エントリポイント: 最適化
# --------------------------------------------------------------------------


def optimize_sequence(
    aa_sequence: str,
    host: CodonHost | str,
    gc_min: float = 40.0,
    gc_max: float = 60.0,
    gc_window: int = 60,
    max_identical_codon_run: int = 2,
    avoid_restriction_sites: dict[str, str] | None = None,
    max_repeat_length: int = 20,
    max_homopolymer: int = 6,
) -> CodonOptimizationResult:
    """`aa_sequence`を`host`の優先コドンで再コード化する（WC-3）。

    Parameters
    ----------
    aa_sequence:
        アミノ酸1文字配列。末尾の`*`は許容し、結果には含めない。
    host:
        `CodonHost`メンバー、登録済みホスト名、またはエイリアス
        （"E. coli", "insect"等）。
    gc_min, gc_max, gc_window:
        コドン選択時にトレーリングウィンドウ（bp）で確認する局所GC%の
        ソフトな許容範囲。
    max_identical_codon_run:
        同一コドンが連続してよい回数の上限（ソフト制約）。
    avoid_restriction_sites:
        回避したい{酵素名: 認識配列}。`None`の場合`DEFAULT_RESTRICTION_SITES`
        を使う。空dict`{}`を渡すと制限酵素チェックを無効化する。
    max_repeat_length, max_homopolymer:
        `detect_synthesis_issues`にそのまま渡され、結果の`issues`に含まれる。

    Returns
    -------
    CodonOptimizationResult
        `optimized_dna_sequence`は`original_aa_sequence`に翻訳し戻せる
        （全ての置換が構成上同義であるため保証される）。CAI・GC%・
        ウィンドウGC%推移・検出された問題を含む。
    """
    protein = aa_sequence.strip().upper()
    if protein.endswith("*"):
        protein = protein[:-1]
    if not protein:
        raise CodonOptimizationError("アミノ酸配列が空です（末尾の'*'を除去した後）。")
    invalid = set(protein) - _VALID_AMINO_ACIDS
    if invalid:
        raise CodonOptimizationError(
            f"アミノ酸配列に不正な文字{sorted(invalid)!r}が含まれています。"
            "標準アミノ酸1文字コード（と任意の末尾'*'）のみ受け付けます。"
        )
    if gc_min < 0 or gc_max > 100 or gc_min >= gc_max:
        raise CodonOptimizationError(f"0 <= gc_min（{gc_min}） < gc_max（{gc_max}） <= 100を満たす必要があります。")
    if gc_window < 3:
        raise CodonOptimizationError(f"gc_windowは3（1コドン分）以上を指定してください（{gc_window}）。")
    if max_identical_codon_run < 1:
        raise CodonOptimizationError(
            f"max_identical_codon_runは1以上を指定してください（{max_identical_codon_run}）。"
        )

    host_key = resolve_host(host)
    sites = avoid_restriction_sites if avoid_restriction_sites is not None else DEFAULT_RESTRICTION_SITES

    codons: list[str] = []
    last_codon: str | None = None
    run_length = 0
    relax_issues: list[CodonOptimizationIssue] = []

    for i, aa in enumerate(protein):
        candidates = _sorted_codons_for_aa(host_key, aa)
        chosen, relaxed = _choose_codon(
            candidates,
            codons=codons,
            last_codon=last_codon,
            run_length=run_length,
            max_run=max_identical_codon_run,
            gc_min=gc_min,
            gc_max=gc_max,
            gc_window=gc_window,
            sites=sites,
        )
        if relaxed:
            pos = i * 3
            relax_issues.append(
                CodonOptimizationIssue(
                    kind="codon_constraint_relaxed",
                    position_start=pos,
                    position_end=pos + 3,
                    detail=f"残基{i + 1}（{aa}）: 制約{relaxed}を緩和してコドンを選択しました。",
                    severity="info",
                )
            )
        codons.append(chosen)
        run_length = run_length + 1 if chosen == last_codon else 1
        last_codon = chosen

    optimized_dna = "".join(codons)
    cai = calculate_cai(optimized_dna, host_key)
    gc_pct = round(gc_fraction(optimized_dna) * 100.0, 1)
    gc_window_percents = _compute_gc_windows(optimized_dna, gc_window)

    issues = detect_synthesis_issues(
        optimized_dna,
        gc_min=gc_min,
        gc_max=gc_max,
        gc_window=gc_window,
        max_repeat_length=max_repeat_length,
        max_homopolymer=max_homopolymer,
        restriction_sites=sites,
    )
    issues.extend(relax_issues)

    return CodonOptimizationResult(
        host=host_key,
        original_aa_sequence=protein,
        optimized_dna_sequence=optimized_dna,
        cai=cai,
        gc_percent=gc_pct,
        gc_window_percents=gc_window_percents,
        issues=issues,
    )


# --------------------------------------------------------------------------
# 合成DNA発注時の問題検出
# --------------------------------------------------------------------------

_HAIRPIN_STEM_LEN = 8
_HAIRPIN_MIN_LOOP = 3
_HAIRPIN_MAX_LOOP = 10


def _detect_homopolymers(seq: str, max_len: int) -> list[CodonOptimizationIssue]:
    issues: list[CodonOptimizationIssue] = []
    n = len(seq)
    i = 0
    while i < n:
        j = i
        while j < n and seq[j] == seq[i]:
            j += 1
        run_len = j - i
        if run_len > max_len:
            issues.append(
                CodonOptimizationIssue(
                    kind="homopolymer",
                    position_start=i,
                    position_end=j,
                    detail=(
                        f"位置{i + 1}-{j}で塩基'{seq[i]}'が{run_len}回連続しています"
                        f"（上限{max_len}）。合成エラーのリスクがあります。"
                    ),
                    severity="warning",
                )
            )
        i = j
    return issues


def _detect_repeats(seq: str, min_len: int) -> list[CodonOptimizationIssue]:
    if min_len < 4 or len(seq) < min_len * 2:
        return []
    seen: dict[str, int] = {}
    hit_starts: set[int] = set()
    for i in range(len(seq) - min_len + 1):
        window = seq[i : i + min_len]
        if window in seen:
            hit_starts.add(seen[window])
            hit_starts.add(i)
        else:
            seen[window] = i
    if not hit_starts:
        return []
    sorted_starts = sorted(hit_starts)
    issues: list[CodonOptimizationIssue] = []
    range_start = sorted_starts[0]
    prev = sorted_starts[0]
    for s in sorted_starts[1:]:
        if s - prev <= 1:
            prev = s
            continue
        issues.append(_repeat_issue(range_start, prev, min_len))
        range_start = s
        prev = s
    issues.append(_repeat_issue(range_start, prev, min_len))
    return issues


def _repeat_issue(range_start: int, range_end: int, min_len: int) -> CodonOptimizationIssue:
    end = range_end + min_len
    return CodonOptimizationIssue(
        kind="repeat",
        position_start=range_start,
        position_end=end,
        detail=(
            f"位置{range_start + 1}-{end}に{min_len}bp以上の反復配列が検出されました。"
            "組換え・合成エラーのリスクがあります。"
        ),
        severity="warning",
    )


def _detect_gc_outliers(seq: str, gc_min: float, gc_max: float, window: int) -> list[CodonOptimizationIssue]:
    if window <= 0 or window > len(seq):
        return []
    issues: list[CodonOptimizationIssue] = []
    for i in range(0, len(seq), window):
        chunk = seq[i : i + window]
        if len(chunk) < window // 2:
            continue
        pct = gc_fraction(chunk) * 100.0
        if pct < gc_min or pct > gc_max:
            issues.append(
                CodonOptimizationIssue(
                    kind="gc_window",
                    position_start=i,
                    position_end=i + len(chunk),
                    detail=(
                        f"位置{i + 1}-{i + len(chunk)}のGC%が{pct:.1f}%です"
                        f"（推奨範囲{gc_min:.0f}-{gc_max:.0f}%）。"
                    ),
                    severity="warning",
                )
            )
    return issues


def _detect_hairpins(seq: str) -> list[CodonOptimizationIssue]:
    issues: list[CodonOptimizationIssue] = []
    n = len(seq)
    stem = _HAIRPIN_STEM_LEN
    i = 0
    while i <= n - 2 * stem - _HAIRPIN_MIN_LOOP:
        arm = seq[i : i + stem]
        rc_arm = str(Seq(arm).reverse_complement())
        search_start = i + stem + _HAIRPIN_MIN_LOOP
        search_end = min(n - stem, i + stem + _HAIRPIN_MAX_LOOP) + stem
        found_at = seq.find(rc_arm, search_start, search_end)
        if found_at != -1:
            issues.append(
                CodonOptimizationIssue(
                    kind="hairpin",
                    position_start=i,
                    position_end=found_at + stem,
                    detail=(
                        f"位置{i + 1}付近に自己相補的な逆位反復（ヘアピン候補）を検出しました。"
                        "二次構造による合成・PCR不良のリスクがあります（粗い検出のため要目視確認）。"
                    ),
                    severity="info",
                )
            )
            i = found_at + stem
        else:
            i += 1
    return issues


def _detect_restriction_sites(seq: str, sites: dict[str, str]) -> list[CodonOptimizationIssue]:
    issues: list[CodonOptimizationIssue] = []
    for enzyme, site_seq in sites.items():
        rc = str(Seq(site_seq).reverse_complement())
        needles = [(site_seq, "+")] if rc == site_seq else [(site_seq, "+"), (rc, "-")]
        for needle, strand_note in needles:
            start = 0
            while True:
                idx = seq.find(needle, start)
                if idx == -1:
                    break
                issues.append(
                    CodonOptimizationIssue(
                        kind="restriction_site",
                        position_start=idx,
                        position_end=idx + len(needle),
                        detail=(
                            f"{enzyme}認識部位（{site_seq}）が位置{idx + 1}-{idx + len(needle)}に"
                            f"検出されました（鎖: {strand_note}）。"
                        ),
                        severity="warning",
                    )
                )
                start = idx + 1
    return issues


def detect_synthesis_issues(
    dna_sequence: str,
    gc_min: float = 40.0,
    gc_max: float = 60.0,
    gc_window: int = 60,
    max_repeat_length: int = 20,
    max_homopolymer: int = 6,
    restriction_sites: dict[str, str] | None = None,
) -> list[CodonOptimizationIssue]:
    """合成DNA発注前に確認すべき問題を検出する。

    ホモポリマー連続、反復配列（cascadingする重複ヒットは1件に統合）、
    GC%ウィンドウ逸脱、ヘアピン候補（粗い逆位反復検出）、制限酵素認識部位
    （両鎖）を検出する。
    """
    seq = dna_sequence.strip().upper()
    sites = restriction_sites if restriction_sites is not None else DEFAULT_RESTRICTION_SITES

    issues: list[CodonOptimizationIssue] = []
    issues.extend(_detect_homopolymers(seq, max_homopolymer))
    issues.extend(_detect_repeats(seq, max_repeat_length))
    issues.extend(_detect_gc_outliers(seq, gc_min, gc_max, gc_window))
    issues.extend(_detect_hairpins(seq))
    issues.extend(_detect_restriction_sites(seq, sites))
    return issues


# --------------------------------------------------------------------------
# 組み込みホストの登録
# --------------------------------------------------------------------------
# ここで初めて登録する: これより上で定義した全てのヘルパー
# （_get_table相当のCODON_USAGE_TABLES参照、_sorted_codons_for_aa等の
# @cacheされたルックアップ）が既に定義済みであることが前提。

register_host_table(CodonHost.ECOLI_K12, _flatten(_ECOLI_K12_NESTED), aliases=_DEFAULT_ALIASES[CodonHost.ECOLI_K12])
register_host_table(CodonHost.HUMAN, _flatten(_HUMAN_NESTED), aliases=_DEFAULT_ALIASES[CodonHost.HUMAN])
register_host_table(CodonHost.SF9, _flatten(_SF9_NESTED), aliases=_DEFAULT_ALIASES[CodonHost.SF9])
