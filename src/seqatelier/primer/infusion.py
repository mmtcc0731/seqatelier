"""In-Fusionプライマー設計（WC-1、設計C）。

In-Fusion（Takara Bio）等のシームレス・ライゲーションフリークローニングは、
末端に短い共通配列（相同領域/homology arm）を持つ2本の直鎖断片
——線状化ベクターとインサート——をPCRで作り、5'->3'エキソヌクレアーゼが
両断片の5'末端を削って露出した相補的一本鎖オーバーハングをアニールさせる
（制限酵素・リガーゼ不要）。このモジュールは、その2断片を作るための
4本のプライマーを設計する:

- ベクター線状化ペア（インバースPCR）: 挿入部位でベクター全体を線状化する。
- インサート増幅ペア: インサートの両端に、ベクター側の接合部と同一の
  5'相同領域（デフォルト15 bp）を付加して増幅する。

挿入位置は`seqatelier.core.sequence.resolve_site`が解決する3種類の指定
（bp番号 / (start, end) / feature名）のいずれかで与える。
"""

from __future__ import annotations

from Bio.Seq import Seq

from seqatelier.core.sequence import LabRecord, resolve_site
from seqatelier.core.types import (
    InFusionDesign,
    InFusionReactionConditions,
    Primer,
    PrimerDesignError,
    PrimerPair,
)
from seqatelier.primer.tm import (
    TmParameters,
    gc_percent,
    pick_binding_length,
    recommend_purification_grade,
    tm_delta_warning,
)

__all__ = ["circular_window", "design_infusion", "format_order_summary", "reverse_complement"]


def circular_window(full_seq: str, start: int, length: int) -> str:
    """0-based、原点跨ぎを許容するcircularウィンドウ読み出し。

    `start`は負の値・配列長を超える値でもよい（`% len(full_seq)`で正規化する）。
    """
    n = len(full_seq)
    if length <= 0:
        return ""
    if length > n:
        raise PrimerDesignError(
            f"{length}bpの領域は{n}bpの環状配列に対して長すぎます（自身と重複します）。"
        )
    start %= n
    end = start + length
    if end <= n:
        return full_seq[start:end]
    return full_seq[start:] + full_seq[: end - n]


def reverse_complement(seq: str) -> str:
    """配列の逆相補鎖を返す。"""
    return str(Seq(seq).reverse_complement())


def _make_primer(
    name: str,
    sequence: str,
    binding_tm: float,
    *,
    homology_arm_length: int = 0,
    binding_start: int | None = None,
    binding_end: int | None = None,
    strand: int | None = None,
    notes: list[str] | None = None,
) -> Primer:
    return Primer(
        name=name,
        sequence=sequence,
        tm_celsius=binding_tm,
        gc_percent=gc_percent(sequence),
        purification=recommend_purification_grade(
            length=len(sequence),
            has_mutation_or_tail=homology_arm_length > 0,
            homology_arm_bp=homology_arm_length,
        ),
        binding_start=binding_start,
        binding_end=binding_end,
        strand=strand,  # type: ignore[arg-type]
        homology_arm_length=homology_arm_length,
        notes=list(notes) if notes else [],
    )


def design_infusion(
    vector: LabRecord,
    insert: LabRecord,
    insertion_site: int | tuple[int, int] | str,
    construct_name: str = "construct",
    homology_arm_bp: int = 15,
    primer_len_min: int = 18,
    primer_len_max: int = 30,
    target_tm: float = 60.0,
    tm_params: TmParameters | None = None,
    annotate_vector: bool = True,
    annotate_insert: bool = True,
) -> InFusionDesign:
    """`vector`の`insertion_site`に`insert`をIn-Fusionクローニングするためのプライマーを設計する。

    Parameters
    ----------
    vector:
        受け側プラスミド。環状（`vector.is_circular`）である必要がある。
    insert:
        挿入する配列。線状鋳型として扱う。
    insertion_site:
        挿入位置。`seqatelier.core.sequence.resolve_site`が解決する3形式
        （bp番号 / (start, end) 1-based inclusive / feature名）のいずれか。
    homology_arm_bp:
        インサートプライマーに付加する5'相同領域の長さ（bp）。In-Fusionの
        標準推奨は15 bp。
    primer_len_min, primer_len_max:
        遺伝子特異的（結合）領域の長さの探索範囲。
    target_tm:
        遺伝子特異的領域のみに対する目標Tm（℃）。相同領域は含まない。
    annotate_vector, annotate_insert:
        Trueの場合、設計したプライマーをprimer_bind featureとして
        対応するレコードのGenBankへ書き戻す（WC-10）。

    Returns
    -------
    InFusionDesign
        ベクター線状化ペア・インサート増幅ペア・想定サイズ・反応条件・警告。

    Raises
    ------
    PrimerDesignError
        ベクターが環状でない、homology_arm_bpが小さすぎる、インサートが
        短すぎる等。
    """
    if not vector.is_circular:
        raise PrimerDesignError(
            f"ベクター'{vector.name}'は線状(linear)として扱われています。In-Fusionは環状ベクターの"
            "インバースPCRを前提とします。record.annotations['topology'] = 'circular'を"
            "設定してください。"
        )
    if homology_arm_bp < 10:
        raise PrimerDesignError(
            f"homology_arm_bpは信頼性の高いアニーリングのため最低10bp必要です（{homology_arm_bp}が指定されました）。"
        )
    if not (0 < primer_len_min <= primer_len_max):
        raise PrimerDesignError(
            f"primer_len_min（{primer_len_min}）とprimer_len_max（{primer_len_max}）の関係が不正です。"
        )

    vector_seq = vector.sequence
    if len(vector_seq) < homology_arm_bp * 2 + primer_len_min * 2:
        raise PrimerDesignError(
            f"ベクターが短すぎます（{len(vector_seq)}bp）。相同領域とプライマー結合領域を"
            "確保できません。"
        )

    insert_seq = insert.sequence
    if len(insert_seq) < primer_len_min:
        raise PrimerDesignError(
            f"インサートが短すぎます（{len(insert_seq)}bp）。最低{primer_len_min}bpの"
            "遺伝子特異的プライマー領域が必要です。"
        )

    site_start, site_end = resolve_site(vector, insertion_site)
    deleted_length = site_end - site_start

    warnings: list[str] = []

    # --- 相同領域: ベクター配列からそのまま切り出す（固定長） -------------
    left_flank = circular_window(vector_seq, site_start - homology_arm_bp, homology_arm_bp)
    right_flank = circular_window(vector_seq, site_end, homology_arm_bp)
    insert_tail_f = left_flank
    insert_tail_r = reverse_complement(right_flank)

    # --- インサート増幅プライマー（遺伝子特異的領域をTmで最適化） ----------
    gene_fwd_template = insert_seq
    gene_fwd_seq, gene_fwd_tm = pick_binding_length(
        gene_fwd_template, primer_len_min, primer_len_max, target_tm, tm_params
    )
    gene_rev_template = reverse_complement(insert_seq)
    gene_rev_seq, gene_rev_tm = pick_binding_length(
        gene_rev_template, primer_len_min, primer_len_max, target_tm, tm_params
    )

    if len(gene_fwd_seq) + len(gene_rev_seq) > len(insert_seq):
        warnings.append(
            f"インサート（{len(insert_seq)}bp）が短いため、フォワード/リバースの"
            "遺伝子特異的領域が重複しています。短いインサート（アニール済みオリゴ等）では想定内です。"
        )

    insert_forward_seq = insert_tail_f + gene_fwd_seq
    insert_reverse_seq = insert_tail_r + gene_rev_seq

    insert_forward = _make_primer(
        f"{construct_name}_INFU_F",
        insert_forward_seq,
        gene_fwd_tm,
        homology_arm_length=homology_arm_bp,
        notes=[
            f"5'側{homology_arm_bp}bpはベクター挿入部位（0-based {site_start}）直前の配列と相同。"
            f"3'側{len(gene_fwd_seq)}bpはインサートの5'末端に結合。"
        ],
    )
    insert_reverse = _make_primer(
        f"{construct_name}_INFU_R",
        insert_reverse_seq,
        gene_rev_tm,
        homology_arm_length=homology_arm_bp,
        notes=[
            f"5'側{homology_arm_bp}bpはベクター挿入部位（0-based {site_end}）直後の配列の逆相補鎖と相同。"
            f"3'側{len(gene_rev_seq)}bpはインサートの3'末端の逆相補鎖に結合。"
        ],
    )

    # --- ベクター線状化プライマー（インバースPCR、Tmで最適化） -------------
    vector_length_after_probe = len(vector_seq) - deleted_length
    window_len = min(primer_len_max, vector_length_after_probe)
    vector_fwd_template = circular_window(vector_seq, site_end, window_len)
    vector_forward_seq, vector_forward_tm = pick_binding_length(
        vector_fwd_template, primer_len_min, primer_len_max, target_tm, tm_params
    )
    vector_rev_template = reverse_complement(circular_window(vector_seq, site_start - window_len, window_len))
    vector_reverse_seq, vector_reverse_tm = pick_binding_length(
        vector_rev_template, primer_len_min, primer_len_max, target_tm, tm_params
    )

    vf_start = site_end % len(vector_seq)
    vf_end = vf_start + len(vector_forward_seq)
    vector_forward = _make_primer(
        f"{construct_name}_LIN_F",
        vector_forward_seq,
        vector_forward_tm,
        binding_start=vf_start if vf_end <= len(vector_seq) else None,
        binding_end=vf_end if vf_end <= len(vector_seq) else None,
        strand=1 if vf_end <= len(vector_seq) else None,
    )
    if vf_end > len(vector_seq):
        warnings.append(
            f"{vector_forward.name}: 結合部位がプラスミドの番号付け原点を跨ぐため、"
            "binding_start/binding_endは未設定です（プライマー配列自体は正しく計算されています）。"
        )

    vr_start = (site_start - len(vector_reverse_seq)) % len(vector_seq)
    vr_end = vr_start + len(vector_reverse_seq)
    vector_reverse = _make_primer(
        f"{construct_name}_LIN_R",
        vector_reverse_seq,
        vector_reverse_tm,
        binding_start=vr_start if vr_end <= len(vector_seq) else None,
        binding_end=vr_end if vr_end <= len(vector_seq) else None,
        strand=-1 if vr_end <= len(vector_seq) else None,
    )
    if vr_end > len(vector_seq):
        warnings.append(
            f"{vector_reverse.name}: 結合部位がプラスミドの番号付け原点を跨ぐため、"
            "binding_start/binding_endは未設定です（プライマー配列自体は正しく計算されています）。"
        )

    vector_length_after = len(vector_seq) - deleted_length
    insert_pcr_product_length = len(insert_seq) + 2 * homology_arm_bp
    predicted_product_length = vector_length_after + len(insert_seq)

    vector_delta_note = tm_delta_warning(vector_forward.tm_celsius, vector_reverse.tm_celsius)
    insert_delta_note = tm_delta_warning(insert_forward.tm_celsius, insert_reverse.tm_celsius)
    if vector_delta_note:
        warnings.append(vector_delta_note)
    if insert_delta_note:
        warnings.append(insert_delta_note)

    vector_linearization = PrimerPair(
        forward=vector_forward,
        reverse=vector_reverse,
        product_size=vector_length_after,
        amplicon_tm_note=vector_delta_note or "",
    )
    insert_amplification = PrimerPair(
        forward=insert_forward,
        reverse=insert_reverse,
        product_size=insert_pcr_product_length,
        amplicon_tm_note=insert_delta_note or "",
    )

    if annotate_vector:
        vector.add_primer_feature(vector_forward, f"{construct_name} In-Fusion vector linearization (forward)")
        vector.add_primer_feature(vector_reverse, f"{construct_name} In-Fusion vector linearization (reverse)")
    if annotate_insert:
        insert.add_primer_feature(insert_forward, f"{construct_name} In-Fusion insert amplification (forward)")
        insert.add_primer_feature(insert_reverse, f"{construct_name} In-Fusion insert amplification (reverse)")

    return InFusionDesign(
        construct_name=construct_name,
        vector_linearization=vector_linearization,
        insert_amplification=insert_amplification,
        insert_length=len(insert_seq),
        vector_length_after=vector_length_after,
        predicted_product_length=predicted_product_length,
        homology_arm_bp=homology_arm_bp,
        reaction_conditions=InFusionReactionConditions(),
        warnings=warnings,
    )


def format_order_summary(design: InFusionDesign) -> str:
    """発注用のMarkdown表を組み立てる。"""
    lines: list[str] = [
        f"# In-Fusion設計サマリー: {design.construct_name}",
        "",
        "## プライマー発注表",
        "",
        "| 名前 | 配列 (5'->3') | 長さ | Tm(結合部) | GC% | 精製 |",
        "|---|---|---|---|---|---|",
    ]
    all_primers: list[Primer] = [
        design.vector_linearization.forward,
        design.vector_linearization.reverse,
        design.insert_amplification.forward,
        design.insert_amplification.reverse,
    ]
    for p in all_primers:
        lines.append(
            f"| {p.name} | {p.sequence} | {p.length} nt | {p.tm_celsius:.1f}°C | "
            f"{p.gc_percent:.1f}% | {p.purification.value.upper()} |"
        )

    lines.extend(
        [
            "",
            "## 想定サイズ",
            "",
            f"- インサート長: {design.insert_length} bp",
            f"- ベクター線状化産物長: {design.vector_length_after} bp",
            f"- インサート増幅産物長（相同領域込み）: {design.insert_amplification.product_size} bp",
            f"- 最終コンストラクト長（予測）: {design.predicted_product_length} bp",
            f"- 相同領域長: {design.homology_arm_bp} bp",
            "",
            "## 反応条件",
            "",
            f"- ベクター量: {design.reaction_conditions.vector_ng} ng相当",
            f"- インサートモル比: ベクターに対し{design.reaction_conditions.insert_molar_ratio}倍",
            f"- 反応温度・時間: {design.reaction_conditions.reaction_temp_celsius}°C, "
            f"{design.reaction_conditions.reaction_time_min}分",
            f"- {design.reaction_conditions.note}",
        ]
    )

    if design.warnings:
        lines.extend(["", "## 警告"])
        lines.extend(f"- {w}" for w in design.warnings)

    return "\n".join(lines) + "\n"
