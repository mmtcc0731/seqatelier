"""SeqAtelier全体で共有する型定義（設計C: 実用性・実験者の使いやすさ最優先）。

このモジュールはSeqAtelier内の他モジュール・BioPythonのいずれにも依存しない。
含まれるもの:

- 例外階層（SeqAtelierErrorを頂点とする）。
- プライマー・プライマーペア・設計結果を表す、JSONシリアライズ可能な
  フラットなdataclass群。全てに`to_dict()`を実装し、MCPサーバー化（WC-7）を
  見据えた構造化I/Oの境界とする。
- ホスト・変異種別・購入グレード等のenum。

座標規約: このモジュール自体は座標系を持たない（`seqatelier.core.sequence`が
1-based公開API / 0-based half-open内部表現の変換を担う）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

# --------------------------------------------------------------------------
# 例外階層
# --------------------------------------------------------------------------


class SeqAtelierError(Exception):
    """SeqAtelierが送出する全エラーの基底クラス。

    これを捕捉することで、「SeqAtelierが理解済みの理由で入力/制約を拒否した」
    場合と、無関係なバグを区別できる。
    """


class SequenceValidationError(SeqAtelierError):
    """配列（またはレコードのメタデータ）がバリデーションに失敗した場合。

    例: 空の配列、想定外の文字を含む、GenBank書き出しに必要な注釈が無い等。
    """


class FeatureNotFoundError(SeqAtelierError):
    """指定した名前のfeatureがレコード上で一意に見つからない場合。"""


class PrimerDesignError(SeqAtelierError):
    """プライマー設計が指定された制約を満たせなかった場合。

    例: 目標Tmに到達する長さが無い、変異/挿入部位が範囲外、線状鋳型の末端に
    近すぎてプライマーを伸長できない等。
    """


class CodonOptimizationError(SeqAtelierError):
    """コドン最適化が指定された制約を満たせなかった場合。"""


class SequenceIndexError(SeqAtelierError):
    """配列インデックス（index.csv）に対する操作が失敗した場合。

    例: 重複ID、未知IDへの更新/削除、壊れた/想定外のCSVヘッダー等。
    """


# --------------------------------------------------------------------------
# Enum・型エイリアス
# --------------------------------------------------------------------------

Strand = Literal[1, -1]
"""核酸鎖の向き。+鎖=1、-鎖=-1。"""


class PurificationGrade(StrEnum):
    """発注時に推奨するオリゴ精製グレード。"""

    DESALT = "desalt"
    HPLC = "hplc"
    PAGE = "page"


class MutationType(StrEnum):
    """QuikChangeプライマーが導入する編集の種類。"""

    SUBSTITUTION = "substitution"
    INSERTION = "insertion"
    DELETION = "deletion"


class CodonHost(StrEnum):
    """コドン使用頻度テーブルが同梱されている発現宿主。

    `StrEnum`なので、`"ecoli_k12"`のような素の文字列（JSON/MCP境界を越えて
    届く値）がメンバーと比較・ハッシュ一致する。`seqatelier.codon.optimize`の
    `register_host_table`でSeqAtelierのソースを変更せずに追加ホストを登録できる。
    """

    ECOLI_K12 = "ecoli_k12"
    HUMAN = "human"
    SF9 = "sf9"


# --------------------------------------------------------------------------
# feature / 位置
# --------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FeatureLocation:
    """0-based half-openのfeature位置。"""

    start: int
    end: int
    strand: Strand = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SequenceFeature:
    """GenBank featureのSeqAtelier内表現。"""

    feature_type: str
    location: FeatureLocation
    qualifiers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """`/label`, `/gene`, `/locus_tag`, `/product`, `/standard_name`の順に
        最初に見つかった値を返す。どれも無ければfeature_typeを返す。"""
        for key in ("label", "gene", "locus_tag", "product", "standard_name"):
            values = self.qualifiers.get(key)
            if values:
                return str(values[0])
        return self.feature_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_type": self.feature_type,
            "location": self.location.to_dict(),
            "qualifiers": {k: list(v) for k, v in self.qualifiers.items()},
            "label": self.label,
        }


# --------------------------------------------------------------------------
# プライマー
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Primer:
    """設計された単一のオリゴヌクレオチド。

    `tm_celsius`は結合領域（5'テールを除く部分）のみのTmであり、
    `gc_percent`/`length`は発注する全長配列（テール込み）に基づく——
    「発注に直結する情報」を最優先するという設計方針による。
    """

    name: str
    sequence: str
    tm_celsius: float
    gc_percent: float
    purification: PurificationGrade
    binding_start: int | None = None
    binding_end: int | None = None
    strand: Strand | None = None
    homology_arm_length: int = 0
    notes: list[str] = field(default_factory=list)
    length: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.length = len(self.sequence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sequence": self.sequence,
            "tm_celsius": self.tm_celsius,
            "gc_percent": self.gc_percent,
            "length": self.length,
            "purification": str(self.purification),
            "binding_start": self.binding_start,
            "binding_end": self.binding_end,
            "strand": self.strand,
            "homology_arm_length": self.homology_arm_length,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class PrimerPair:
    """フォワード/リバースの1組で、単一の産物を増幅するプライマーペア。"""

    forward: Primer
    reverse: Primer
    product_size: int
    amplicon_tm_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "forward": self.forward.to_dict(),
            "reverse": self.reverse.to_dict(),
            "product_size": self.product_size,
            "amplicon_tm_note": self.amplicon_tm_note,
        }


# --------------------------------------------------------------------------
# In-Fusion
# --------------------------------------------------------------------------


@dataclass(slots=True)
class InFusionReactionConditions:
    """In-Fusion反応のベンチデフォルト条件。"""

    vector_ng: float = 50.0
    insert_molar_ratio: float = 2.0
    reaction_temp_celsius: float = 50.0
    reaction_time_min: int = 15
    note: str = (
        "In-Fusionクローニング反応: 線状化ベクター 50 ng相当 + インサートをベクターに"
        "対しモル比2倍で混合し、50°Cで15分間インキュベートする。反応液はそのまま"
        "コンピテント細胞の形質転換に使用可能（精製・脱塩は不要）。"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InFusionDesign:
    """In-Fusionプライマー設計の結果（WC-1）。"""

    construct_name: str
    vector_linearization: PrimerPair
    insert_amplification: PrimerPair
    insert_length: int
    vector_length_after: int
    predicted_product_length: int
    homology_arm_bp: int
    reaction_conditions: InFusionReactionConditions
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct_name": self.construct_name,
            "vector_linearization": self.vector_linearization.to_dict(),
            "insert_amplification": self.insert_amplification.to_dict(),
            "insert_length": self.insert_length,
            "vector_length_after": self.vector_length_after,
            "predicted_product_length": self.predicted_product_length,
            "homology_arm_bp": self.homology_arm_bp,
            "reaction_conditions": self.reaction_conditions.to_dict(),
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# QuikChange
# --------------------------------------------------------------------------


@dataclass(slots=True)
class QuikChangeDesign:
    """QuikChangeプライマー設計の結果（WC-2）。"""

    mutation_type: MutationType
    mutation_description: str
    primer_pair: PrimerPair
    sequencing_primer_note: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_type": str(self.mutation_type),
            "mutation_description": self.mutation_description,
            "primer_pair": self.primer_pair.to_dict(),
            "sequencing_primer_note": self.sequencing_primer_note,
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# コドン最適化
# --------------------------------------------------------------------------


@dataclass(slots=True)
class CodonOptimizationIssue:
    """合成DNA発注時に注意すべき、検出された1件の問題。"""

    kind: str
    position_start: int
    position_end: int
    detail: str
    severity: str = "warning"  # "info" | "warning" | "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CodonOptimizationResult:
    """コドン最適化の実行結果（WC-3）。"""

    host: str
    original_aa_sequence: str
    optimized_dna_sequence: str
    cai: float | None
    gc_percent: float
    gc_window_percents: list[float] = field(default_factory=list)
    issues: list[CodonOptimizationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "original_aa_sequence": self.original_aa_sequence,
            "optimized_dna_sequence": self.optimized_dna_sequence,
            "cai": self.cai,
            "gc_percent": self.gc_percent,
            "gc_window_percents": list(self.gc_window_percents),
            "issues": [issue.to_dict() for issue in self.issues],
        }


# --------------------------------------------------------------------------
# 配列インデックス（WC-4）
# --------------------------------------------------------------------------


@dataclass(slots=True)
class IndexEntry:
    """`data/index.csv`の1行分のエントリ。"""

    id: str
    name: str
    kind: str
    path: str
    length: int
    description: str = ""
    tags: str = ""
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# 線形テキストマップ（WC-9）
# --------------------------------------------------------------------------


@dataclass(slots=True)
class LinearMapLine:
    """線形マップの折り返し1ブロック分（配列行 + featureバー/翻訳行）。"""

    start_position: int  # 1-based
    sequence_line: str
    feature_bars: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LinearMap:
    """`seqatelier.display.linear_map.render_linear_map`の結果。"""

    record_name: str
    length: int
    is_circular: bool
    region_start: int
    region_end: int
    lines: list[LinearMapLine] = field(default_factory=list)
    legend: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_name": self.record_name,
            "length": self.length,
            "is_circular": self.is_circular,
            "region_start": self.region_start,
            "region_end": self.region_end,
            "lines": [line.to_dict() for line in self.lines],
            "legend": self.legend,
            "text": self.render_text(),
        }

    def render_text(self) -> str:
        """実験ノートへの貼り付け用に、マップ全体を1つのテキストへ整形する。"""
        topology = "circular" if self.is_circular else "linear"
        header = (
            f"{self.record_name} | {self.length} bp | {topology} | "
            f"表示範囲 {self.region_start}-{self.region_end}"
        )
        parts: list[str] = [header, ""]
        for line in self.lines:
            parts.append(line.sequence_line)
            parts.extend(line.feature_bars)
            parts.append("")
        if self.legend:
            parts.append(self.legend)
        return "\n".join(parts).rstrip("\n") + "\n"
