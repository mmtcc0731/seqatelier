"""QuikChangeプライマー設計（WC-2、設計C）: 点変異・挿入・欠失、および

残基番号を指定するだけで変異体を設計できる`design_point_mutation_by_codon`
（実験者が「245番目のGlnをArgにしたい」から直接プライマーへ辿り着けるように
するための、案C（実用性最優先）の核となる関数）。

古典的なQuikChange（Stratagene/Agilent）設計に従う: 変異を含む完全に相補的な
1組のプライマーで、環状鋳型全体を直線的に増幅する（ウェットラボでは続けて
DpnIでメチル化された親鋳型を消化する）。プライマーは25-45 nt、Tm >= 約78°C
（nearest-neighbor法）、変異を中央に置き両側に10-15塩基程度の正しい配列が
挟まる、という設計を目指す。
"""

from __future__ import annotations

from Bio.Seq import Seq

from seqatelier.core.sequence import LabRecord, resolve_site
from seqatelier.core.types import (
    CodonHost,
    FeatureNotFoundError,
    MutationType,
    Primer,
    PrimerDesignError,
    PrimerPair,
    QuikChangeDesign,
)
from seqatelier.primer.infusion import circular_window, reverse_complement
from seqatelier.primer.tm import (
    TmParameters,
    calc_tm,
    gc_percent,
    recommend_purification_grade,
)

__all__ = ["design_point_mutation_by_codon", "design_quikchange", "format_order_summary"]

_LARGE_INSERTION_WARNING_BP = 20
_LONG_PRIMER_WARNING_NT = 45


def _fetch_upstream(seq: str, pos: int, length: int, *, circular: bool) -> str:
    if circular:
        return circular_window(seq, pos - length, length)
    start = pos - length
    if start < 0:
        raise PrimerDesignError(
            f"変異部位が鋳型の5'末端に近すぎ、上流に{length}bp確保できません"
            "（鋳型は線状として扱われています）。鋳型が本来circularなプラスミドであれば、"
            "record.annotations['topology'] = 'circular'を設定してください。"
        )
    return seq[start:pos]


def _fetch_downstream(seq: str, pos: int, length: int, *, circular: bool) -> str:
    if circular:
        return circular_window(seq, pos, length)
    end = pos + length
    if end > len(seq):
        raise PrimerDesignError(
            f"変異部位が鋳型の3'末端に近すぎ、下流に{length}bp確保できません"
            "（鋳型は線状として扱われています）。"
        )
    return seq[pos:end]


def _grow_mutant_oligo(
    template_seq: str,
    region_start: int,
    region_end: int,
    replacement: str,
    *,
    circular: bool,
    target_tm: float,
    flank_min: int,
    flank_max: int,
    tm_params: TmParameters | None,
) -> tuple[str, float, int]:
    """変異部位を中心に、目標Tmに達するまで対称にフランクを伸ばす。

    Returns
    -------
    (oligo, tm, flank_used)
    """
    best: tuple[str, float, int] | None = None
    for flank in range(flank_min, flank_max + 1):
        try:
            left = _fetch_upstream(template_seq, region_start, flank, circular=circular)
            right = _fetch_downstream(template_seq, region_end, flank, circular=circular)
        except PrimerDesignError:
            break
        candidate = left + replacement + right
        tm = calc_tm(candidate, tm_params)
        if best is None or abs(tm - target_tm) < abs(best[1] - target_tm):
            best = (candidate, tm, flank)
        if tm >= target_tm:
            break
    if best is None:
        raise PrimerDesignError(
            "QuikChangeプライマーを設計できませんでした。変異部位が鋳型の末端に近すぎる"
            "可能性があります。flank_max_bpを増やすか、鋳型が実際には環状プラスミドで"
            "あればtopology='circular'を確認してください。"
        )
    return best


def design_quikchange(
    template: LabRecord,
    site: int | tuple[int, int] | str,
    new_sequence: str = "",
    construct_name: str = "mutant",
    flank_min_bp: int = 12,
    flank_max_bp: int = 25,
    target_flank_tm: float = 78.0,
    tm_params: TmParameters | None = None,
    annotate: bool = True,
) -> QuikChangeDesign:
    """`template`の`site`に変異（置換・挿入・欠失）を導入するQuikChangeプライマーを設計する。

    Parameters
    ----------
    site:
        変異部位。`seqatelier.core.sequence.resolve_site`が解決する3形式
        （bp番号 / (start, end) 1-based inclusive / feature名）のいずれか。
    new_sequence:
        置き換え後の配列。空文字列は欠失を意味する。`site`が単一点
        （挿入点、region長0）の場合は挿入を意味する。
    flank_min_bp, flank_max_bp:
        変異部位の両側に確保する正しい配列の長さの探索範囲（対称）。
    target_flank_tm:
        プライマー全体（フランク+変異部）に対する目標Tm（℃）。Agilentの
        古典的QuikChangeプロトコルは約78°C以上を推奨する。

    Returns
    -------
    QuikChangeDesign
        変異種別、説明、プライマーペア、シーケンシング確認の提案、警告。

    Raises
    ------
    PrimerDesignError
        変異部位が範囲外、変異が無変化（no-op）、または鋳型末端に近すぎて
        設計できない場合。
    """
    template_seq = template.sequence
    circular = template.is_circular
    region_start, region_end = resolve_site(template, site)

    if not (0 <= region_start <= region_end <= template.length):
        raise PrimerDesignError(
            f"変異部位[{region_start}, {region_end})が{template.length}bpの鋳型に対して不正です。"
        )

    replacement = new_sequence.strip().upper()
    region_length = region_end - region_start

    if region_length == 0 and not replacement:
        raise PrimerDesignError(
            "変異部位の範囲が0bpで、new_sequenceも空です。変異になっていません。"
        )

    if region_length > 0 and not replacement:
        mutation_type = MutationType.DELETION
        original_fragment = template_seq[region_start:region_end]
        description = f"{construct_name}: 位置{region_start + 1}-{region_end}（{original_fragment}）を欠失"
    elif region_length == 0:
        mutation_type = MutationType.INSERTION
        description = f"{construct_name}: 位置{region_start}の直後に{replacement}を挿入"
    else:
        mutation_type = MutationType.SUBSTITUTION
        original_fragment = template_seq[region_start:region_end]
        if original_fragment == replacement:
            raise PrimerDesignError(
                f"new_sequence'{replacement}'は鋳型の該当位置と同一です。変異になっていません。"
            )
        description = (
            f"{construct_name}: 位置{region_start + 1}-{region_end}を"
            f"'{original_fragment}'から'{replacement}'に置換"
        )

    if not (0 < flank_min_bp <= flank_max_bp):
        raise PrimerDesignError(
            f"flank_min_bp（{flank_min_bp}）とflank_max_bp（{flank_max_bp}）の関係が不正です。"
        )

    oligo, tm, flank_used = _grow_mutant_oligo(
        template_seq,
        region_start,
        region_end,
        replacement,
        circular=circular,
        target_tm=target_flank_tm,
        flank_min=flank_min_bp,
        flank_max=flank_max_bp,
        tm_params=tm_params,
    )

    warnings: list[str] = []
    if tm < target_flank_tm:
        warnings.append(
            f"flank_max_bp（{flank_max_bp}bp）まで伸ばしても目標Tm（{target_flank_tm:.1f}°C）に"
            f"到達しませんでした（到達Tm: {tm:.1f}°C）。flank_max_bpを増やすことを検討してください。"
        )
    if mutation_type == MutationType.INSERTION and len(replacement) > _LARGE_INSERTION_WARNING_BP:
        warnings.append(
            f"挿入配列が{len(replacement)}bpあります。QuikChange型の挿入は通常"
            f"~{_LARGE_INSERTION_WARNING_BP}bpまでが実用的です（それ以上は合成品質・コストが"
            "悪化します）。より大きな挿入にはIn-Fusion（seqatelier.primer.infusion）を検討してください。"
        )
    if len(oligo) > _LONG_PRIMER_WARNING_NT:
        warnings.append(
            f"プライマー長が{len(oligo)}ntです（推奨上限{_LONG_PRIMER_WARNING_NT}nt）。"
            "合成品質やアニーリング特異性に注意してください。"
        )

    forward_seq = oligo
    reverse_seq = reverse_complement(oligo)

    tm_assumption_note = (
        "Tmは変異導入後の配列（このプライマー自身の配列）に対する完全一致（perfect match）を"
        "仮定したnearest-neighbor計算値です。鋳型（変異前の親プラスミド）とのミスマッチ部分の"
        "実際のアニーリング挙動はこのTmには反映されていません。"
    )

    def _build(name: str, sequence: str) -> Primer:
        return Primer(
            name=name,
            sequence=sequence,
            tm_celsius=tm,
            gc_percent=gc_percent(sequence),
            purification=recommend_purification_grade(length=len(sequence), has_mutation_or_tail=True),
            notes=[tm_assumption_note],
        )

    forward = _build(f"{construct_name}_QC_F", forward_seq)
    reverse = _build(f"{construct_name}_QC_R", reverse_seq)

    left_start = region_start - flank_used
    right_end = region_end + flank_used
    if left_start >= 0 and right_end <= template.length:
        forward.binding_start = left_start
        forward.binding_end = right_end
        forward.strand = 1
        reverse.binding_start = left_start
        reverse.binding_end = right_end
        reverse.strand = -1
    else:
        warnings.append(
            f"{forward.name}/{reverse.name}: 結合部位が鋳型の番号付け原点を跨ぐため、"
            "binding_start/binding_endは未設定です（プライマー配列自体は正しく計算されています）。"
        )

    sequencing_note = (
        f"変異確認用シーケンシングプライマーは、変異部位（0-based位置{region_start}付近）から"
        "100-150bp上流の位置に設計することを推奨します（変異部位そのものに近すぎるプライマーは"
        "サンガーシーケンシングの波形が乱れやすい先頭領域に変異が来てしまうため）。"
    )

    primer_pair = PrimerPair(
        forward=forward,
        reverse=reverse,
        product_size=template.length - region_length + len(replacement),
        amplicon_tm_note=f"設計Tm: {tm:.1f}°C（目標 {target_flank_tm:.1f}°C）",
    )

    if annotate:
        template.add_primer_feature(forward, f"{construct_name} QuikChange (forward)")
        template.add_primer_feature(reverse, f"{construct_name} QuikChange (reverse)")

    return QuikChangeDesign(
        mutation_type=mutation_type,
        mutation_description=description,
        primer_pair=primer_pair,
        sequencing_primer_note=sequencing_note,
        warnings=warnings,
    )


def design_point_mutation_by_codon(
    template: LabRecord,
    residue_number: int,
    new_amino_acid: str,
    host: CodonHost | str = CodonHost.ECOLI_K12,
    cds_feature_label: str | None = None,
    cds_start_bp: int | None = None,
    construct_name: str | None = None,
    flank_min_bp: int = 12,
    flank_max_bp: int = 25,
    target_flank_tm: float = 78.0,
    tm_params: TmParameters | None = None,
    annotate: bool = True,
) -> QuikChangeDesign:
    """アミノ酸残基番号を指定するだけで点変異体のプライマーを設計する。

    「245番目の残基をArgにしたい」という、実験者の頭の中にある発想から
    直接プライマー設計へ辿り着くための関数（案C: 残基指定による変異体設計）。

    Parameters
    ----------
    residue_number:
        1-basedのアミノ酸残基番号（CDSの開始Metを1とする）。
    new_amino_acid:
        変異後のアミノ酸1文字コード。
    host:
        新しいコドンの選択に使う宿主のコドン使用頻度（`seqatelier.codon.optimize.best_codon`）。
    cds_feature_label, cds_start_bp:
        CDSの開始位置の指定方法。どちらも省略した場合、`template`上の
        ラベル"CDS"のfeature（`feature_type="CDS"`）を探す。
        `cds_start_bp`は1-based（ATGのAの位置）。

    Returns
    -------
    QuikChangeDesign
        `design_quikchange`と同じ形。`mutation_description`はアミノ酸変異の
        表記（例: "Q92R"）を含む形に上書きされる。
    """
    from seqatelier.codon.optimize import best_codon  # 循環importを避けるため遅延import

    if residue_number < 1:
        raise PrimerDesignError(
            f"residue_numberは1以上を指定してください（{residue_number}が指定されました）。"
        )
    new_aa = new_amino_acid.strip().upper()
    if len(new_aa) != 1 or new_aa not in "ACDEFGHIKLMNPQRSTVWY":
        raise PrimerDesignError(
            f"new_amino_acidは標準アミノ酸1文字コードで指定してください（'{new_amino_acid}'は不正です）。"
        )

    strand = 1
    translation_table = 1
    if cds_start_bp is not None:
        if cds_feature_label is not None:
            raise PrimerDesignError("Specify cds_feature_label or cds_start_bp, not both.")
        cds_start_0 = cds_start_bp - 1
        codon_start_0 = cds_start_0 + (residue_number - 1) * 3
        codon_end_0 = codon_start_0 + 3
    else:
        label = cds_feature_label or "CDS"
        feature = template.find_feature(label, feature_type="CDS")
        if feature is None:
            raise FeatureNotFoundError(
                f"CDS feature'{label}'が見つかりません。cds_feature_labelまたは"
                "cds_start_bp（ATGの1-based位置）を明示的に指定してください。"
            )
        raw = next(raw for raw, typed in zip(
            (f for f in template.record.features if f.location is not None), template.features_typed, strict=True
        ) if typed == feature)
        assert raw.location is not None
        strand = raw.location.strand
        if strand not in (1, -1):
            raise PrimerDesignError("CDS must have one known strand.")
        try:
            offset = int(raw.qualifiers.get("codon_start", ["1"])[0]) - 1
            translation_table = int(raw.qualifiers.get("transl_table", ["1"])[0])
        except ValueError as exc:
            raise PrimerDesignError("Invalid CDS codon_start or transl_table qualifier.") from exc
        if offset not in (0, 1, 2):
            raise PrimerDesignError("CDS codon_start must be 1, 2 or 3.")
        if translation_table not in (1, 11):
            raise PrimerDesignError("Host codon selection currently supports translation tables 1 and 11 only.")
        coding_positions = list(raw.location)
        position = offset + (residue_number - 1) * 3
        positions = coding_positions[position:position + 3]
        if len(positions) != 3:
            raise PrimerDesignError("Residue number is outside the CDS, including its codon_start offset.")
        if max(positions) - min(positions) != 2:
            raise PrimerDesignError("The selected codon crosses a joined CDS boundary; contiguous replacement is unsupported.")
        codon_start_0, codon_end_0 = min(positions), max(positions) + 1
        cds_start_0 = min(coding_positions)
    if codon_end_0 > template.length or codon_start_0 < 0:
        raise PrimerDesignError(
            f"残基番号{residue_number}に対応するコドン位置が鋳型の範囲外です"
            f"（鋳型長{template.length}bp、CDS開始位置0-based {cds_start_0}）。"
        )

    original_codon = template.sequence[codon_start_0:codon_end_0]
    if strand == -1:
        original_codon = reverse_complement(original_codon)
    original_aa = str(Seq(original_codon).translate(table=str(translation_table)))
    new_codon = best_codon(new_aa, host)

    name = construct_name or f"{template.name}_{original_aa}{residue_number}{new_aa}"

    design = design_quikchange(
        template,
        site=(codon_start_0 + 1, codon_end_0),
        new_sequence=reverse_complement(new_codon) if strand == -1 else new_codon,
        construct_name=name,
        flank_min_bp=flank_min_bp,
        flank_max_bp=flank_max_bp,
        target_flank_tm=target_flank_tm,
        tm_params=tm_params,
        annotate=annotate,
    )
    design.mutation_description = (
        f"{name}: 残基{residue_number} {original_aa}→{new_aa}（コドン {original_codon}→{new_codon}）"
    )
    return design


def format_order_summary(design: QuikChangeDesign) -> str:
    """発注用のMarkdown表を組み立てる。"""
    fwd = design.primer_pair.forward
    rev = design.primer_pair.reverse
    lines = [
        f"# QuikChange設計サマリー: {design.mutation_description}",
        "",
        f"- 変異種別: {design.mutation_type.value}",
        "",
        "## プライマー発注表",
        "",
        "| 名前 | 配列 (5'->3') | 長さ | Tm | GC% | 精製 |",
        "|---|---|---|---|---|---|",
    ]
    for p in (fwd, rev):
        lines.append(
            f"| {p.name} | {p.sequence} | {p.length} nt | {p.tm_celsius:.1f}°C | "
            f"{p.gc_percent:.1f}% | {p.purification.value.upper()} |"
        )
    lines.extend(
        [
            "",
            f"- 産物（変異後プラスミド）長: {design.primer_pair.product_size} bp",
            f"- {design.primer_pair.amplicon_tm_note}",
            "",
            "## 変異確認",
            "",
            f"- {design.sequencing_primer_note}",
        ]
    )
    if design.warnings:
        lines.extend(["", "## 警告"])
        lines.extend(f"- {w}" for w in design.warnings)
    return "\n".join(lines) + "\n"
