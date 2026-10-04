"""GenBank I/Oと`LabRecord`ラッパー（設計C: 実用性・実験者の使いやすさ最優先）。

このモジュールが定めるSeqAtelier全体の規約:

1. **座標は公開APIでは1-based、内部（0-based half-open）はモジュール内で
   変換する。** `resolve_site()`が3種類の位置指定（bp番号 / (start, end) /
   feature名）を受け取り、常に0-based half-openの`(start, end)`を返す。
2. **プラスミドは環状である。** `LabRecord.is_circular`が`False`（デフォルト、
   線状）か`True`かを判定し、`LabRecord.region()`が原点を跨ぐ読み出しを
   透過的に処理する。
3. **保存形式はGenBank一本（WC-10）。** SeqAtelier独自の注釈（用途・Tm・GC%等）は
   `/note`修飾子に`seqatelier:key=value;...`という単一の文字列としてエンコードする。
   SnapGene・ApE等、GenBankを読める既存ツールとの互換性を保つ。
"""

from __future__ import annotations

from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

from seqatelier.core.types import (
    FeatureLocation,
    FeatureNotFoundError,
    Primer,
    SequenceFeature,
    SequenceValidationError,
    Strand,
)

__all__ = [
    "SEQATELIER_NOTE_PREFIX",
    "LabRecord",
    "as_int",
    "parse_seqatelier_note",
    "resolve_site",
]

SEQATELIER_NOTE_PREFIX = "seqatelier:"
"""SeqAtelier独自メタデータを`/note`修飾子に格納する際のプレフィックス。"""

_MAX_LOCUS_NAME_LENGTH = 40  # BioPython/SnapGene は16文字超を正常に扱う
_UNAMBIGUOUS_BASES = frozenset("ACGT")
_AMBIGUOUS_BASES = frozenset("URYSWKMBDHVN")


def parse_seqatelier_note(note: str) -> dict[str, str]:
    """`"seqatelier:key=value;key2=value2"`形式のnote文字列をdictに変換する。

    プレフィックスが無い、またはキー=値の形になっていない部分は無視する。
    """
    result: dict[str, str] = {}
    if not note.startswith(SEQATELIER_NOTE_PREFIX):
        return result
    body = note[len(SEQATELIER_NOTE_PREFIX) :]
    for pair in body.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        result[key.strip()] = value.strip()
    return result


def as_int(position: object) -> int:
    """BioPythonのfeature位置終端(`ExactPosition`等)を素の`int`に変換する。

    `SeqFeature.location.start`/`.end`はBioPython自身の型注釈では抽象基底
    クラス`Position`としてしか型付けされておらず、静的型チェッカーは
    int変換可能とは認識しない（実際に返ってくる具象位置——`ExactPosition`
    等——は`__index__`を実装しており、実行時には`int(...)`が正しく動く）。
    この既知のスタブの隙間を、呼び出し側に`# type: ignore`を散らす代わりに
    ここ1箇所に閉じ込める。
    """
    return int(position)  # type: ignore[arg-type]


class LabRecord:
    """BioPythonの`SeqRecord`を実験者向けの操作でラップするクラス。

    プライマー設計・コドン最適化・線形マップの各モジュールは、生の`SeqRecord`
    ではなく`LabRecord`を受け取る/返すことを基本とする。
    """

    def __init__(self, record: SeqRecord, source_path: Path | None = None) -> None:
        self.record = record
        self.source_path = source_path

    # ------------------------------------------------------------------
    # 基本プロパティ
    # ------------------------------------------------------------------

    @property
    def sequence(self) -> str:
        """配列全体を大文字の`str`で返す。"""
        if self.record.seq is None:
            raise SequenceValidationError(
                f"レコード'{self.name}'に配列データがありません（record.seqがNone）。"
            )
        return str(self.record.seq).upper()

    @property
    def length(self) -> int:
        return len(self.sequence)

    @property
    def name(self) -> str:
        return self.record.name or self.record.id or "unnamed"

    @property
    def is_circular(self) -> bool:
        """`annotations["topology"] == "circular"`かどうか。未設定時はFalse（線状）。"""
        topology = str(self.record.annotations.get("topology", "linear")).lower()
        return topology == "circular"

    @property
    def features_typed(self) -> list[SequenceFeature]:
        """レコード上の全featureを`SequenceFeature`のリストとして返す。

        位置情報を持たないfeature（`location is None`）は除外する。
        """
        result: list[SequenceFeature] = []
        for feat in self.record.features:
            if feat.location is None:
                continue
            raw_strand = feat.location.strand
            strand: Strand = -1 if raw_strand == -1 else 1
            loc = FeatureLocation(
                start=as_int(feat.location.start),
                end=as_int(feat.location.end),
                strand=strand,
            )
            result.append(
                SequenceFeature(
                    feature_type=feat.type,
                    location=loc,
                    qualifiers={k: list(v) for k, v in feat.qualifiers.items()},
                )
            )
        return result

    def find_feature(self, name: str, feature_type: str | None = None) -> SequenceFeature | None:
        """ラベルでfeatureを検索する（完全一致優先、次に部分一致）。

        Raises
        ------
        FeatureNotFoundError
            一致が複数あり、一意に決まらない場合。
        """
        target = name.strip().lower()
        candidates = self.features_typed
        if feature_type is not None:
            candidates = [f for f in candidates if f.feature_type == feature_type]

        exact = [f for f in candidates if f.label.lower() == target]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise FeatureNotFoundError(
                f"'{name}'に完全一致するfeatureが{len(exact)}件あり、一意に決まりません。"
                "より具体的なラベルを指定してください。"
            )

        substr = [f for f in candidates if target in f.label.lower()]
        if len(substr) == 1:
            return substr[0]
        if len(substr) > 1:
            raise FeatureNotFoundError(
                f"'{name}'を含むfeatureが{len(substr)}件あり、一意に決まりません。"
                "より具体的なラベルを指定してください。"
            )
        return None

    def region(self, start: int, end: int) -> str:
        """0-based half-openの範囲`[start, end)`の配列を返す。

        `start > end`の場合、環状レコード（`is_circular`）でのみ許容され、
        原点を跨いで読み出す（`seq[start:] + seq[:end]`）。
        """
        seq = self.sequence
        n = len(seq)
        if start <= end:
            if not (0 <= start <= end <= n):
                raise SequenceValidationError(
                    f"範囲[{start}, {end})が{n}bpのレコードに対して不正です。"
                )
            return seq[start:end]
        if not self.is_circular:
            raise SequenceValidationError(
                f"start({start}) > end({end})は原点を跨ぐ読み出しを意味しますが、"
                f"レコード'{self.name}'は線状（linear）です。環状プラスミドの場合は"
                "record.annotations['topology'] = 'circular' を設定してください。"
            )
        if not (0 <= start < n and 0 <= end <= n):
            raise SequenceValidationError(
                f"範囲[{start}, {end})（原点跨ぎ）が{n}bpのレコードに対して不正です。"
            )
        return seq[start:] + seq[:end]

    def translate_region(self, start: int, end: int, strand: Strand = 1) -> str:
        """0-based half-open範囲`[start, end)`を翻訳したアミノ酸配列を返す。"""
        region_seq = self.region(start, end)
        if len(region_seq) % 3 != 0:
            raise SequenceValidationError(
                f"翻訳対象領域の長さ（{len(region_seq)}bp）が3の倍数ではありません。"
                "リーディングフレームを確認してください。"
            )
        seq_obj = Seq(region_seq)
        if strand == -1:
            seq_obj = seq_obj.reverse_complement()
        return str(seq_obj.translate(table="Standard", to_stop=False))

    def add_primer_feature(self, primer: Primer, purpose: str) -> None:
        """`primer`をprimer_bind featureとしてGenBankレコードに書き戻す（WC-10）。

        `primer.binding_start`/`binding_end`が未設定（キメラプライマー等、
        単一の鋳型上に連続した結合部位を持たない場合）の場合は何もしない。
        """
        if primer.binding_start is None or primer.binding_end is None:
            return
        strand = primer.strand if primer.strand is not None else 1
        location = SimpleLocation(primer.binding_start, primer.binding_end, strand=strand)
        note_value = (
            f"{SEQATELIER_NOTE_PREFIX}purpose={purpose};"
            f"tm={primer.tm_celsius:.1f};gc={primer.gc_percent:.1f}"
        )
        feature = SeqFeature(
            location,
            type="primer_bind",
            qualifiers={"label": [primer.name], "note": [note_value]},
        )
        self.record.features.append(feature)

    # ------------------------------------------------------------------
    # 読み込み・書き出し
    # ------------------------------------------------------------------

    @classmethod
    def from_genbank(cls, path: str | Path) -> LabRecord:
        """単一レコードのGenBankファイルを読み込む。"""
        file_path = Path(path)
        if not file_path.is_file():
            raise SequenceValidationError(
                f"GenBankファイルが見つかりません: {file_path}。パスを確認してください。"
            )
        try:
            record = SeqIO.read(file_path, "genbank")
        except ValueError as exc:
            raise SequenceValidationError(
                f"{file_path}の読み込みに失敗しました: {exc}。"
                "ファイルが単一レコードの正しいGenBank形式であることを確認してください。"
            ) from exc
        return cls(record=record, source_path=file_path)

    def to_genbank(self, path: str | Path | None = None) -> Path:
        """GenBank形式でアトミックに書き出す（`path`省略時は読み込み元に上書き）。"""
        out_path = Path(path) if path is not None else self.source_path
        if out_path is None:
            raise SequenceValidationError(
                "保存先パスが指定されていません。path引数を渡すか、"
                "from_genbank()で読み込んだレコードを使ってください。"
            )
        if "molecule_type" not in self.record.annotations:
            self.record.annotations["molecule_type"] = "DNA"
        if len(self.record.name) > _MAX_LOCUS_NAME_LENGTH:
            raise SequenceValidationError(
                f"record.name'{self.record.name}'は{len(self.record.name)}文字です。"
                f"GenBankのLOCUS名は最大{_MAX_LOCUS_NAME_LENGTH}文字です。"
                "record.nameを短くしてから保存してください。"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_name(out_path.name + ".tmp")
        with open(tmp_path, "w") as handle:
            SeqIO.write(self.record, handle, "genbank")
        tmp_path.replace(out_path)
        self.source_path = out_path
        return out_path

    @classmethod
    def from_sequence(
        cls,
        sequence: str,
        name: str,
        description: str = "",
        circular: bool = False,
    ) -> LabRecord:
        """生の配列文字列から新しい`LabRecord`を作成する。"""
        seq = sequence.strip().upper()
        if not seq:
            raise SequenceValidationError("空の配列からLabRecordを作成することはできません。")
        invalid = set(seq) - _UNAMBIGUOUS_BASES - _AMBIGUOUS_BASES
        if invalid:
            raise SequenceValidationError(
                f"配列に不正な文字{sorted(invalid)!r}が含まれています。"
            )
        record_name = name if len(name) <= _MAX_LOCUS_NAME_LENGTH else name[:_MAX_LOCUS_NAME_LENGTH]
        record = SeqRecord(Seq(seq), id=name, name=record_name, description=description)
        record.annotations["molecule_type"] = "DNA"
        record.annotations["topology"] = "circular" if circular else "linear"
        return cls(record=record, source_path=None)


def resolve_site(record: LabRecord, site: int | tuple[int, int] | str) -> tuple[int, int]:
    """位置指定を0-based half-openの`(start, end)`に解決する。

    **注意（`int`と`tuple`とで座標基準が異なる）**: `tuple`形式は1-based
    inclusiveだが、`int`形式は0-basedの挿入点である。同じ「位置」の意味で
    混同しないこと。

    - `int`: **0-based**の純粋な挿入点。`(site, site)`をそのまま返す
      （例: `site=245`は0-based配列上でインデックス245の直前——すなわち
      bp245とbp246の間——に挿入する）。有効範囲は`0 <= site <= record.length`
      （`site=0`はレコード先頭への挿入、`site=record.length`は末尾への挿入）。
      このバリデーションは0-basedとして正しい。
    - `tuple[int, int]`: **1-based inclusive**の範囲`(first_bp, last_bp)`。
      `(first_bp - 1, last_bp)`という0-based half-openに変換する。
    - `str`: featureのラベル。`record.find_feature()`で解決した位置を返す。
    """
    if isinstance(site, bool):
        raise TypeError(f"siteはint・tuple・strのいずれかである必要があります（bool {site!r}）。")

    if isinstance(site, int):
        if not (0 <= site <= record.length):
            raise SequenceValidationError(
                f"位置{site}は{record.length}bpのレコードに対して範囲外です"
                f"（0以上{record.length}以下である必要があります）。"
            )
        return site, site

    if isinstance(site, tuple):
        if len(site) != 2:
            raise TypeError("siteのtupleは(start, end)の2要素である必要があります。")
        start, end = site
        if not (1 <= start <= end <= record.length):
            raise SequenceValidationError(
                f"範囲({start}, {end})が{record.length}bpのレコードに対して不正です。"
                f"1 <= start <= end <= {record.length}を満たす必要があります。"
            )
        return start - 1, end

    if isinstance(site, str):
        feature = record.find_feature(site)
        if feature is None:
            raise FeatureNotFoundError(
                f"feature'{site}'がレコード'{record.name}'上に見つかりません。"
            )
        return feature.location.start, feature.location.end

    raise TypeError(f"siteはint・tuple・strのいずれかである必要があります（{type(site).__name__}）。")
