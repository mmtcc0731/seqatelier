"""プライマーのTm・GC%計算（設計C）。

`Bio.SeqUtils.MeltingTemp.Tm_NN`（nearest-neighbor法）の薄いラッパー。
In-Fusion・QuikChangeそれぞれのベンチでの標準条件をプリセットとして提供する
（`TmParameters.infusion_default()` / `quikchange_default()` / `pcr_default()`）。

Tmは常に「結合領域のみ」（5'テールを除く）に対して計算する。In-Fusionの
相同領域（homology arm）はアニーリングに寄与しないため、Tm計算には含めない。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from Bio.Seq import Seq
from Bio.SeqUtils import gc_fraction
from Bio.SeqUtils.MeltingTemp import Tm_NN

from seqatelier.core.types import PrimerDesignError, PurificationGrade, SequenceValidationError


def _tm_nn(seq: Seq, **kwargs: Any) -> float:
    """`Bio.SeqUtils.MeltingTemp.Tm_NN`への、明示的に型付けされた薄いラッパー。

    `Tm_NN`の各引数はBioPython自身のソースでは無注釈で、静的型チェッカーは
    各パラメータの（整数の）デフォルト値から型を推論するため、実際のMg2+緩衝
    PCR反応が必要とするfloatの濃度（例: `Mg=1.5`）を拒否してしまう
    （実装自体はfloatで正しく計算する: `Tm_NN(Seq("..."), Mg=1.5, ...)`は
    実行時に正常なfloatを返すことを確認済み）。この既知のスタブの隙間を
    ここ1箇所に閉じ込め、戻り値の型を明示する。
    """
    return Tm_NN(seq, **kwargs)  # type: ignore[no-any-return]

__all__ = [
    "TmParameters",
    "calc_tm",
    "gc_percent",
    "pick_binding_length",
    "recommend_purification_grade",
    "tm_delta_warning",
]


@dataclass(slots=True)
class TmParameters:
    """`Tm_NN`に渡す反応条件。ベンチで実際に使う緩衝液組成を表す。

    `dntp_mm`はdNTPs（dATP+dCTP+dGTP+dTTPの4種）の合計濃度である。市販の
    高忠実度ポリメラーゼ用マスターミックスは各dNTPを0.2 mMずつ、合計0.8 mM
    含むことが一般的（`Tm_NN`が要求する`dNTPs`引数もこの合計濃度）。
    """

    na_mm: float = 50.0
    k_mm: float = 0.0
    mg_mm: float = 2.0
    dntp_mm: float = 0.8
    primer_conc_nm: float = 250.0
    saltcorr: int = 7

    @classmethod
    def infusion_default(cls) -> TmParameters:
        """In-Fusion（HDクローニング）用のPCR条件: Mg2+ 2.0 mM。"""
        return cls(na_mm=50.0, k_mm=0.0, mg_mm=2.0, dntp_mm=0.8, primer_conc_nm=250.0, saltcorr=7)

    @classmethod
    def quikchange_default(cls) -> TmParameters:
        """QuikChange（PfuUltra等、K+緩衝液系）用の条件。"""
        return cls(na_mm=0.0, k_mm=50.0, mg_mm=2.0, dntp_mm=0.8, primer_conc_nm=250.0, saltcorr=7)

    @classmethod
    def pcr_default(cls) -> TmParameters:
        """汎用PCR条件（高忠実度ポリメラーゼの標準的な緩衝液組成)。"""
        return cls(na_mm=50.0, k_mm=0.0, mg_mm=1.5, dntp_mm=0.8, primer_conc_nm=250.0, saltcorr=7)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gc_percent(sequence: str) -> float:
    """`sequence`のGC含量をパーセント（0-100）で返す。"""
    seq = sequence.strip().upper()
    if not seq:
        raise SequenceValidationError("空の配列のGC%は計算できません。配列を確認してください。")
    return round(gc_fraction(seq) * 100.0, 1)


def calc_tm(binding_sequence: str, params: TmParameters | None = None) -> float:
    """`binding_sequence`（結合領域のみ、5'テールを含めない）のTmを計算する。

    Raises
    ------
    SequenceValidationError
        配列が6nt未満、またはACGT以外の文字を含む場合。
    """
    seq = binding_sequence.strip().upper()
    if len(seq) < 6:
        raise PrimerDesignError(
            f"Tm計算には最低6ntの結合配列が必要です（{len(seq)}ntが指定されました）。"
            "プライマーの結合領域（5'テールを除いた部分）を長くしてください。"
        )
    invalid = set(seq) - set("ACGT")
    if invalid:
        raise SequenceValidationError(
            f"配列に不正な文字{sorted(invalid)!r}が含まれています。Tm計算はACGTのみに対応します。"
        )
    p = params or TmParameters()
    tm = _tm_nn(
        Seq(seq),
        dnac1=p.primer_conc_nm,
        dnac2=0,
        Na=p.na_mm,
        K=p.k_mm,
        Mg=p.mg_mm,
        dNTPs=p.dntp_mm,
        saltcorr=p.saltcorr,
    )
    return round(float(tm), 2)


def pick_binding_length(
    template: str,
    length_min: int = 18,
    length_max: int = 30,
    target_tm: float = 60.0,
    params: TmParameters | None = None,
) -> tuple[str, float]:
    """`template`の先頭から伸ばしていき、目標Tmに到達する最短の長さを選ぶ。

    `template[:length]`をlength_minからlength_maxまで順に試し、
    `target_tm`以上に達した時点の長さをそのまま採用する（最短優先）。
    到達しない場合は、試した中で最もTmが目標に近い長さを返す。

    Returns
    -------
    (sequence, tm)
        選ばれた結合配列とそのTm。
    """
    if length_min < 6:
        raise PrimerDesignError(f"length_minは6以上を指定してください（{length_min}が指定されました）。")
    if length_max < length_min:
        raise PrimerDesignError(
            f"length_max（{length_max}）はlength_min（{length_min}）以上である必要があります。"
        )
    if len(template) < length_min:
        raise PrimerDesignError(
            f"鋳型が短すぎます（{len(template)}nt）。最低{length_min}nt必要です。"
        )

    upper_bound = min(length_max, len(template))
    best_seq = template[:length_min]
    best_tm = calc_tm(best_seq, params)
    for length in range(length_min, upper_bound + 1):
        candidate = template[:length]
        tm = calc_tm(candidate, params)
        best_seq, best_tm = candidate, tm
        if tm >= target_tm:
            return candidate, tm
    return best_seq, best_tm


def recommend_purification_grade(
    length: int,
    has_mutation_or_tail: bool = False,
    homology_arm_bp: int = 0,
) -> PurificationGrade:
    """プライマー長・変異/テールの有無・相同領域長から精製グレードを推奨する。

    実験室での経験則: 長いオリゴ・相同領域を持つオリゴほど、合成中の
    欠失変異体（n-1等）の混入比率が上がるため、より厳しい精製が必要になる。
    """
    if length >= 60 or homology_arm_bp >= 25:
        return PurificationGrade.PAGE
    if length >= 35 or has_mutation_or_tail or homology_arm_bp > 0:
        return PurificationGrade.HPLC
    return PurificationGrade.DESALT


def tm_delta_warning(fwd_tm: float, rev_tm: float, max_delta: float = 2.0) -> str | None:
    """フォワード/リバースのTm差が`max_delta`を超える場合、警告文を返す。"""
    delta = abs(fwd_tm - rev_tm)
    if delta > max_delta:
        return (
            f"フォワード/リバースプライマーのTm差が{delta:.1f}°Cあります"
            f"（Fwd={fwd_tm:.1f}°C, Rev={rev_tm:.1f}°C）。{max_delta:.1f}°C以内を推奨します。"
        )
    return None
