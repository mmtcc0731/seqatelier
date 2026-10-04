"""プライマー発注管理。

SeqAtelier の設計結果（InFusionDesign / QuikChangeDesign 等）を、発注業者への
コピペ用シンプルCSV と、内部履歴用の詳細記録に分けて保存する。

ディレクトリ構造:
    data/orders/
    ├── index.csv                        全発注の一覧（date, id, name, ...）
    └── 2026-07-04_construct_slug/       発注ごとにサブディレクトリ
        ├── order_simple.csv             primer_name, sequence の2列（発注業者コピペ用）
        ├── order_extended.csv           + scale, purification, mods（拡張列）
        ├── detail.json                  全情報（Tm, GC, 設計根拠, target plasmid等）
        └── README.md                    人間可読サマリ

これにより:
- Eurofins 等のフォームには order_simple.csv or order_extended.csv をコピペ
- 発注後 detail.json を参照して「なぜこのプライマーを設計したか」を後から確認可能
- index.csv を grep することで過去発注を検索
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from seqatelier.core.types import (
    InFusionDesign,
    Primer,
    QuikChangeDesign,
    SequenceValidationError,
)

# --------------------------------------------------------------------------
# データモデル
# --------------------------------------------------------------------------


@dataclass(slots=True)
class OrderPrimer:
    """発注1本分のプライマー情報。

    設計時のパラメータ（Tm, GC%, purification 推奨等）と、発注時に業者が
    必要とする情報（scale, modifications 等）を両方保持する。
    """

    name: str
    sequence: str
    length: int = field(init=False)
    tm_celsius: float | None = None
    gc_percent: float | None = None
    scale: str = "50nmol"  # Eurofins スタンダードオリゴのデフォルト
    purification: str = "OPC"  # 標準的な In-Fusion / QuikChange 用途
    modifications_5: str = ""
    modifications_3: str = ""
    modifications_internal: str = ""
    purpose: str = ""
    target_plasmid_id: str = ""
    target_position_bp: int | None = None
    design_method: str = ""
    design_notes: str = ""

    def __post_init__(self) -> None:
        self.length = len(self.sequence)
        if not self.name.strip():
            raise SequenceValidationError("OrderPrimer.name is empty.")
        if not re.fullmatch(r"[ACGTURYSWKMBDHVN]+", self.sequence.upper()):
            raise SequenceValidationError(
                f"OrderPrimer.sequence contains non-IUPAC characters: {self.sequence!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_seqatelier_primer(
        cls,
        primer: Primer,
        *,
        purpose: str = "",
        target_plasmid_id: str = "",
        target_position_bp: int | None = None,
        design_method: str = "",
        design_notes: str = "",
        scale: str = "50nmol",
    ) -> OrderPrimer:
        """seqatelier.core.types.Primer から OrderPrimer に変換する。

        Primer が持つ purification 推奨（DESALT/HPLC/PAGE）を Eurofins 表記
        （salt-free/OPC/HPLC）にマッピングする。
        """
        purification_map = {
            "DESALT": "salt-free",
            "OPC": "OPC",
            "HPLC": "HPLC",
            "PAGE": "HPLC",  # PAGE は 2024-06-01 で終了、HPLC 推奨
        }
        purification_raw = str(primer.purification).upper()
        purification = purification_map.get(purification_raw, "OPC")

        pos_bp: int | None = None
        if target_position_bp is not None:
            pos_bp = target_position_bp
        elif primer.binding_start is not None:
            pos_bp = primer.binding_start + 1  # 0-based → 1-based

        return cls(
            name=primer.name,
            sequence=primer.sequence,
            tm_celsius=primer.tm_celsius,
            gc_percent=primer.gc_percent,
            scale=scale,
            purification=purification,
            purpose=purpose,
            target_plasmid_id=target_plasmid_id,
            target_position_bp=pos_bp,
            design_method=design_method,
            design_notes=(design_notes or "\n".join(primer.notes)),
        )


@dataclass(slots=True)
class OrderBatch:
    """1回の発注（= 一連の関連プライマー）をまとめる単位。

    典型的には In-Fusion 4本、QuikChange 2本、あるいはユーザーが手動で
    まとめた任意の本数のプライマー。
    """

    name: str  # 人間可読な名前（例: "pTest mCherry In-Fusion"）
    primers: list[OrderPrimer] = field(default_factory=list)
    description: str = ""
    vendor: str = "eurofins_genomics_jp"
    vendor_service: str = "standard_oligo"  # or "pcready", "hts_oligo" etc.
    created: str = ""  # YYYY-MM-DD ISO date
    campaign_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""  # <date>_<slug>, set by save_order_batch

    def add_primer(self, primer: OrderPrimer) -> None:
        self.primers.append(primer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "vendor": self.vendor,
            "vendor_service": self.vendor_service,
            "created": self.created,
            "campaign_code": self.campaign_code,
            "metadata": self.metadata,
            "primers": [p.to_dict() for p in self.primers],
        }


# --------------------------------------------------------------------------
# 保存・読込
# --------------------------------------------------------------------------

_INDEX_FIELDS = [
    "id",
    "date",
    "name",
    "vendor",
    "primer_count",
    "description",
    "path",
]


def _slugify(text: str) -> str:
    """発注名からファイル名安全な slug を作る（英数と_-のみ、他は_）。"""
    s = re.sub(r"[^\w\-]+", "_", text.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:50] if s else "order"


def _write_simple_csv(batch: OrderBatch, path: Path) -> None:
    """発注業者へのコピペ用: primer_name, sequence の 2 列のみ。"""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["primer_name", "sequence"])
        for primer in batch.primers:
            writer.writerow([primer.name, primer.sequence])


def _write_extended_csv(batch: OrderBatch, path: Path) -> None:
    """発注業者フォームの拡張列に対応: scale, purification, mods 付き。"""
    fields = [
        "primer_name",
        "sequence",
        "length",
        "scale",
        "purification",
        "mod_5",
        "mod_3",
        "mod_internal",
        "tm_celsius",
        "gc_percent",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(fields)
        for primer in batch.primers:
            writer.writerow(
                [
                    primer.name,
                    primer.sequence,
                    primer.length,
                    primer.scale,
                    primer.purification,
                    primer.modifications_5,
                    primer.modifications_3,
                    primer.modifications_internal,
                    "" if primer.tm_celsius is None else f"{primer.tm_celsius:.1f}",
                    "" if primer.gc_percent is None else f"{primer.gc_percent:.1f}",
                ]
            )


def _write_detail_json(batch: OrderBatch, path: Path) -> None:
    """全情報を保持する JSON。設計根拠・target plasmid・設計メタデータ含む。"""
    with path.open("w", encoding="utf-8") as fh:
        json.dump(batch.to_dict(), fh, ensure_ascii=False, indent=2)


def _write_readme(batch: OrderBatch, path: Path) -> None:
    """人間可読なサマリ Markdown。発注時に印刷して手元に置くための資料。"""
    lines: list[str] = [
        f"# 発注 {batch.id or batch.name}",
        "",
        f"- 発注日: {batch.created}",
        f"- 業者: {batch.vendor} ({batch.vendor_service})",
        f"- プライマー本数: {len(batch.primers)}",
    ]
    if batch.description:
        lines.append(f"- 説明: {batch.description}")
    if batch.campaign_code:
        lines.append(f"- キャンペーンコード: `{batch.campaign_code}`")
    if batch.metadata:
        lines.append("")
        lines.append("## 設計メタデータ")
        for k, v in batch.metadata.items():
            lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## プライマー一覧")
    lines.append("")
    lines.append(
        "| 名前 | 配列 (5'→3') | 長さ | Tm | GC% | Scale | 精製 | 用途 |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|"
    )
    for p in batch.primers:
        tm = f"{p.tm_celsius:.1f}°C" if p.tm_celsius is not None else "-"
        gc = f"{p.gc_percent:.1f}%" if p.gc_percent is not None else "-"
        lines.append(
            f"| {p.name} | `{p.sequence}` | {p.length} nt | {tm} | {gc} | "
            f"{p.scale} | {p.purification} | {p.purpose} |"
        )
    lines.append("")
    lines.append("## 修飾")
    lines.append("")
    has_mods = any(
        p.modifications_5 or p.modifications_3 or p.modifications_internal
        for p in batch.primers
    )
    if has_mods:
        for p in batch.primers:
            mods = []
            if p.modifications_5:
                mods.append(f"5': {p.modifications_5}")
            if p.modifications_3:
                mods.append(f"3': {p.modifications_3}")
            if p.modifications_internal:
                mods.append(f"internal: {p.modifications_internal}")
            if mods:
                lines.append(f"- **{p.name}**: {'; '.join(mods)}")
    else:
        lines.append("なし")
    lines.append("")
    lines.append("## 発注ファイル")
    lines.append("")
    lines.append("- `order_simple.csv` — primer_name, sequence の2列（コピペ用）")
    lines.append("- `order_extended.csv` — 拡張列（scale, purification, modifications 付き）")
    lines.append("- `detail.json` — 全情報（設計履歴含む）")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _update_index(index_path: Path, batch: OrderBatch, batch_dir: Path) -> None:
    """data/orders/index.csv に新しい発注のエントリを追記する。"""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    if index_path.exists():
        with index_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            entries = list(reader)
    entries = [e for e in entries if e.get("id") != batch.id]
    entries.append(
        {
            "id": batch.id,
            "date": batch.created,
            "name": batch.name,
            "vendor": batch.vendor,
            "primer_count": str(len(batch.primers)),
            "description": batch.description,
            "path": str(batch_dir.relative_to(index_path.parent)),
        }
    )
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    with index_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_INDEX_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for entry in entries:
            writer.writerow({k: entry.get(k, "") for k in _INDEX_FIELDS})


def save_order_batch(
    batch: OrderBatch,
    base_dir: str | Path,
    *,
    today: str | None = None,
) -> Path:
    """発注 batch を base_dir 配下に保存する。

    Args:
        batch: 保存する OrderBatch
        base_dir: data/orders/ 相当のディレクトリ
        today: YYYY-MM-DD 形式の日付。省略時は今日の日付。

    Returns:
        作成されたサブディレクトリのパス
    """
    base = Path(base_dir)
    date_str = today or batch.created or _dt.date.today().isoformat()
    batch.created = date_str
    slug = _slugify(batch.name)
    batch_id = f"{date_str}_{slug}"
    batch.id = batch_id

    batch_dir = base / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    _write_simple_csv(batch, batch_dir / "order_simple.csv")
    _write_extended_csv(batch, batch_dir / "order_extended.csv")
    _write_detail_json(batch, batch_dir / "detail.json")
    _write_readme(batch, batch_dir / "README.md")
    _update_index(base / "index.csv", batch, batch_dir)

    return batch_dir


def load_order_batch(batch_dir: str | Path) -> OrderBatch:
    """detail.json から OrderBatch を復元する。"""
    detail_path = Path(batch_dir) / "detail.json"
    with detail_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    batch = OrderBatch(
        id=data.get("id", ""),
        name=data["name"],
        description=data.get("description", ""),
        vendor=data.get("vendor", "eurofins_genomics_jp"),
        vendor_service=data.get("vendor_service", "standard_oligo"),
        created=data.get("created", ""),
        campaign_code=data.get("campaign_code", ""),
        metadata=data.get("metadata", {}),
    )
    for p in data.get("primers", []):
        # length は __post_init__ で再計算されるため取り除く
        p = {k: v for k, v in p.items() if k != "length"}
        batch.primers.append(OrderPrimer(**p))
    return batch


def list_order_batches(base_dir: str | Path) -> list[dict[str, str]]:
    """base_dir/index.csv を読み、発注一覧を返す。"""
    index_path = Path(base_dir) / "index.csv"
    if not index_path.exists():
        return []
    with index_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


# --------------------------------------------------------------------------
# 設計結果 → OrderBatch 変換ヘルパー
# --------------------------------------------------------------------------


def _from_pair(
    fwd: Primer,
    rev: Primer,
    *,
    fwd_purpose: str,
    rev_purpose: str,
    target_plasmid_id: str,
    design_method: str,
) -> list[OrderPrimer]:
    return [
        OrderPrimer.from_seqatelier_primer(
            fwd,
            purpose=fwd_purpose,
            target_plasmid_id=target_plasmid_id,
            design_method=design_method,
        ),
        OrderPrimer.from_seqatelier_primer(
            rev,
            purpose=rev_purpose,
            target_plasmid_id=target_plasmid_id,
            design_method=design_method,
        ),
    ]


def from_infusion_design(
    design: InFusionDesign,
    *,
    name: str | None = None,
    description: str = "",
    target_plasmid_id: str = "",
    vendor: str = "eurofins_genomics_jp",
    vendor_service: str = "standard_oligo",
    campaign_code: str = "",
) -> OrderBatch:
    """InFusionDesign（4本のプライマー）を OrderBatch に変換する。"""
    batch = OrderBatch(
        name=name or f"In-Fusion {design.construct_name}",
        description=description,
        vendor=vendor,
        vendor_service=vendor_service,
        campaign_code=campaign_code,
        metadata={
            "design_method": "In-Fusion",
            "construct_name": design.construct_name,
            "insert_length": design.insert_length,
            "vector_length_after": design.vector_length_after,
            "predicted_product_length": design.predicted_product_length,
            "homology_arm_bp": design.homology_arm_bp,
            "reaction_conditions": design.reaction_conditions.to_dict(),
        },
    )
    batch.primers.extend(
        _from_pair(
            design.vector_linearization.forward,
            design.vector_linearization.reverse,
            fwd_purpose="In-Fusion vector linearization forward",
            rev_purpose="In-Fusion vector linearization reverse",
            target_plasmid_id=target_plasmid_id,
            design_method="seqatelier.primer.infusion.design_infusion",
        )
    )
    batch.primers.extend(
        _from_pair(
            design.insert_amplification.forward,
            design.insert_amplification.reverse,
            fwd_purpose="In-Fusion insert amplification forward (with 5' homology arm)",
            rev_purpose="In-Fusion insert amplification reverse (with 5' homology arm)",
            target_plasmid_id=target_plasmid_id,
            design_method="seqatelier.primer.infusion.design_infusion",
        )
    )
    return batch


def from_quikchange_design(
    design: QuikChangeDesign,
    *,
    name: str | None = None,
    description: str = "",
    target_plasmid_id: str = "",
    vendor: str = "eurofins_genomics_jp",
    vendor_service: str = "standard_oligo",
    campaign_code: str = "",
) -> OrderBatch:
    """QuikChangeDesign（2本のプライマー）を OrderBatch に変換する。"""
    batch = OrderBatch(
        name=name or f"QuikChange {design.mutation_description}",
        description=description,
        vendor=vendor,
        vendor_service=vendor_service,
        campaign_code=campaign_code,
        metadata={
            "design_method": "QuikChange",
            "mutation_type": str(design.mutation_type),
            "mutation_description": design.mutation_description,
            "sequencing_primer_note": design.sequencing_primer_note,
        },
    )
    batch.primers.extend(
        _from_pair(
            design.primer_pair.forward,
            design.primer_pair.reverse,
            fwd_purpose=f"QuikChange forward ({design.mutation_description})",
            rev_purpose=f"QuikChange reverse ({design.mutation_description})",
            target_plasmid_id=target_plasmid_id,
            design_method="seqatelier.primer.quikchange.design_quikchange",
        )
    )
    return batch
