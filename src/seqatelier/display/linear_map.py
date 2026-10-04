"""線形テキストシーケンスマップ（WC-9、設計C）。

`LabRecord`をラップされたテキストとして描画する: 各行を1-basedの開始位置で
prefixし、その行に重なる各feature用に1トラックずつ（向きを示す`>`/`<`バー
+ラベル）表示、単純位置（非compound）のCDS featureはさらに下段に
コドン先頭塩基の位置に合わせたアミノ酸配列を併記する。

制限（黙って誤魔化さず明記する）:

- 単純（非compound）位置のfeatureのみ翻訳トラックを持つ。スプライスされた
  （joinされた）CDSはスパン+ラベルのトラックのみで、翻訳は付かない。
- このモジュールはレコードに既に存在するfeatureのみを描画する。制限酵素
  部位・ORF等、未注釈のものは検出しない。
"""

from __future__ import annotations

from Bio.SeqFeature import CompoundLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from seqatelier.core.sequence import LabRecord, as_int
from seqatelier.core.types import LinearMap, LinearMapLine, SeqAtelierError, SequenceFeature

__all__ = ["LinearMapError", "render_linear_map", "render_linear_map_text"]

_MIN_LINE_WIDTH = 20
_LABEL_MAX_LEN = 40


class LinearMapError(SeqAtelierError):
    """線形マップのレンダリングパラメータが不正な場合に送出される。"""


def _label_for(feature: SequenceFeature) -> str:
    label = feature.label
    return label if len(label) <= _LABEL_MAX_LEN else label[: _LABEL_MAX_LEN - 3] + "..."


def _assign_rows(spans: list[tuple[int, int]]) -> list[int]:
    """重なるfeatureが別の表示行になるよう、貪欲な区間スケジューリングで行を割り当てる。"""
    order = sorted(range(len(spans)), key=lambda i: spans[i][0])
    row_ends: list[int] = []
    assigned = [0] * len(spans)
    for i in order:
        s, e = spans[i]
        for row, end in enumerate(row_ends):
            if s >= end:
                row_ends[row] = e
                assigned[i] = row
                break
        else:
            row_ends.append(e)
            assigned[i] = len(row_ends) - 1
    return assigned


def _find_raw_feature(raw_record: SeqRecord, feat: SequenceFeature) -> SeqFeature | None:
    for raw in raw_record.features:
        if raw.location is None or raw.type != feat.feature_type:
            continue
        if as_int(raw.location.start) == feat.location.start and as_int(raw.location.end) == feat.location.end:
            return raw
    return None


def _translate_positions(raw_feat: SeqFeature, raw_record: SeqRecord, start: int, end: int) -> dict[int, str]:
    """コドン先頭の絶対(0-based)位置 -> アミノ酸1文字、のマップを返す。"""
    location = raw_feat.location
    if location is None:
        raise SeqAtelierError("内部エラー: locationがNoneのfeatureを翻訳しようとしました。")
    strand = location.strand or 1
    protein = str(location.extract(raw_record.seq).translate(table="Standard", to_stop=False))
    positions: dict[int, str] = {}
    if strand == 1:
        for i, aa in enumerate(protein):
            pos = start + 3 * i
            if pos + 3 > end:
                break
            positions[pos] = aa
    else:
        for i, aa in enumerate(protein):
            pos = end - 3 * (i + 1)
            if pos < start:
                break
            positions[pos] = aa
    return positions


def _render_block(
    full_seq: str,
    block_start: int,
    block_end: int,
    features: list[SequenceFeature],
    rows: list[int],
    translations: dict[int, dict[int, str]],
    gutter_width: int,
    region_start: int,
) -> LinearMapLine:
    position_label = str(block_start + 1).rjust(gutter_width)
    sequence_line = f"{position_label} {full_seq[block_start:block_end]}"
    block_width = block_end - block_start
    indent = " " * (gutter_width + 1)

    active = [
        (idx, f)
        for idx, f in enumerate(features)
        if f.location.start < block_end and f.location.end > block_start
    ]
    active_rows = sorted({rows[idx] for idx, _ in active})

    feature_bars: list[str] = []
    for row in active_rows:
        row_feats = [(idx, f) for idx, f in active if rows[idx] == row]
        bar = [" "] * block_width
        labels: list[str] = []
        row_aa: list[str] | None = None
        for idx, f in row_feats:
            seg_start = max(f.location.start, block_start) - block_start
            seg_end = min(f.location.end, block_end) - block_start
            marker = ">" if f.location.strand == 1 else "<"
            for col in range(seg_start, seg_end):
                bar[col] = marker
            if f.location.start >= block_start:
                labels.append(_label_for(f))
            elif block_start == region_start:
                # このfeatureは表示範囲の外（region_startより前）から始まっている。
                # 開始行が描画されないため、先頭ブロックに限り「(cont.)」付きで
                # ラベルを表示する（さもないとラベルが一切表示されない）。
                labels.append(f"(cont.) {_label_for(f)}")
            aa_positions = translations.get(idx)
            if aa_positions:
                if row_aa is None:
                    row_aa = [" "] * block_width
                for abs_pos, aa in aa_positions.items():
                    if block_start <= abs_pos < block_end:
                        row_aa[abs_pos - block_start] = aa
        bar_str = "".join(bar).rstrip()
        suffix = f"  {', '.join(labels)}" if labels else ""
        feature_bars.append(f"{indent}{bar_str}{suffix}")
        if row_aa is not None:
            feature_bars.append(f"{indent}{''.join(row_aa).rstrip()}")

    return LinearMapLine(start_position=block_start + 1, sequence_line=sequence_line, feature_bars=feature_bars)


def render_linear_map(
    record: LabRecord,
    region: tuple[int, int] | None = None,
    line_width: int = 60,
    show_translation: bool = True,
) -> LinearMap:
    """`record`を線形テキストマップとして描画する（feature・翻訳併記、WC-9）。

    Parameters
    ----------
    region:
        1-based inclusiveの表示範囲。`None`（デフォルト）ならレコード全体。
        featureは範囲と少しでも重なれば表示され、範囲内の部分のみ描画される。
        ラベルは、そのfeatureが実際に開始する行にのみ表示される。ただし、
        feature の開始位置が表示範囲より前にある場合（表示範囲の途中から
        featureが継続している場合）は、先頭ブロックに限り`"(cont.) "`を
        前置してラベルを表示する（さもないとそのfeatureのラベルが表示範囲内に
        一度も現れない）。
    line_width:
        1行あたりの表示塩基数。20以上を指定する。
    show_translation:
        Trueの場合、単純位置のCDS featureの下段にアミノ酸配列を併記する。

    Raises
    ------
    LinearMapError
        `line_width < 20`、または`region`が範囲外・逆転している場合。
    """
    if line_width < _MIN_LINE_WIDTH:
        raise LinearMapError(
            f"line_widthは{_MIN_LINE_WIDTH}以上を指定してください（{line_width}が指定されました）。"
        )

    full_seq = record.sequence
    seq_length = record.length

    if region is None:
        display_start, display_end = 1, seq_length
    else:
        display_start, display_end = region
        if not (1 <= display_start <= display_end <= seq_length):
            raise LinearMapError(
                f"表示範囲[{display_start}, {display_end}]が{seq_length}bpのレコードに対して不正です。"
            )

    s0 = display_start - 1
    e0 = display_end

    all_features = record.features_typed
    overlapping = [f for f in all_features if f.location.start < e0 and f.location.end > s0]
    spans = [(f.location.start, f.location.end) for f in overlapping]
    rows = _assign_rows(spans)

    translations: dict[int, dict[int, str]] = {}
    if show_translation:
        raw_record = record.record
        for idx, feat in enumerate(overlapping):
            if feat.feature_type != "CDS":
                continue
            raw_feat = _find_raw_feature(raw_record, feat)
            if raw_feat is None or raw_feat.location is None or isinstance(raw_feat.location, CompoundLocation):
                continue
            translations[idx] = _translate_positions(raw_feat, raw_record, feat.location.start, feat.location.end)

    gutter_width = len(str(display_end))
    lines: list[LinearMapLine] = []
    block_start = s0
    while block_start < e0:
        block_end = min(block_start + line_width, e0)
        lines.append(
            _render_block(full_seq, block_start, block_end, overlapping, rows, translations, gutter_width, s0)
        )
        block_start = block_end

    legend = "> : +鎖、< : -鎖。CDSの下段はアミノ酸配列（1文字コード、コドン先頭位置に配置）。"
    return LinearMap(
        record_name=record.name,
        length=seq_length,
        is_circular=record.is_circular,
        region_start=display_start,
        region_end=display_end,
        lines=lines,
        legend=legend,
    )


def render_linear_map_text(
    record: LabRecord,
    region: tuple[int, int] | None = None,
    line_width: int = 60,
    show_translation: bool = True,
) -> str:
    """`render_linear_map`の結果をそのままテキストとして返す便利関数。"""
    return render_linear_map(
        record, region=region, line_width=line_width, show_translation=show_translation
    ).render_text()
