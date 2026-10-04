"""ファイルパスベースの便利関数（MCPサーバー化を見据えた境界層、WC-7）。

`seqatelier.primer`/`seqatelier.codon`/`seqatelier.display`/`seqatelier.core.index`の各設計・
解析関数は`LabRecord`（BioPythonの`SeqRecord`をラップしたオブジェクト）を
受け取る/返す設計になっている。これはPythonから直接呼ぶ分には自然だが、
MCPサーバー（stdin/stdoutをJSONで越境するプロセス境界）越しにはBioPython
オブジェクトを直接やり取りできない——という「MCP境界のギャップ」がある。

このモジュールは、その境界の両側を橋渡しする薄いラッパー層である:

- 入力: ファイルパス（`str`）・座標（`int`/`tuple[int, int]`/`str`）・
  プリミティブ引数（`str`/`int`/`float`）のみを受け取る。
- 内部: `LabRecord.from_genbank()`でファイルを読み込み、対応する設計・解析
  関数を呼ぶ。
- 出力: 各結果dataclassの`to_dict()`（フラットな`dict`、JSONシリアライズ
  可能）のみを返す。

このモジュールが呼ぶ設計関数は、GenBankファイルへの書き戻し
（`annotate_vector`/`annotate_insert`/`annotate`引数、WC-10）をデフォルトで
行うが、その変更は呼び出し元が渡した`LabRecord`のメモリ上の状態にのみ
反映され、ここでは`to_genbank()`を呼ばないため**ディスクには保存されない**。
変更を永続化したい場合は、Python APIを直接使い、明示的に`to_genbank()`を
呼ぶこと（この関数群は「読み取り→設計→結果を返す」までを担い、書き込みの
要否は呼び出し側の判断に委ねる）。
"""

from __future__ import annotations

from typing import Any

from seqatelier.codon.optimize import optimize_sequence
from seqatelier.core.index import register_from_genbank, search
from seqatelier.core.sequence import LabRecord
from seqatelier.core.types import SequenceValidationError
from seqatelier.display.linear_map import render_linear_map
from seqatelier.primer.infusion import design_infusion
from seqatelier.primer.quikchange import design_point_mutation_by_codon, design_quikchange
from seqatelier.primer.tm import TmParameters, calc_tm, gc_percent

__all__ = [
    "calc_tm_api",
    "infusion_from_files",
    "linear_map_from_file",
    "optimize_codons_api",
    "point_mutation_from_file",
    "quikchange_from_file",
    "register_genbank",
    "search_index",
]


def _normalize_site(site: int | tuple[int, int] | list[int] | str) -> int | tuple[int, int] | str:
    """JSON経由で届いた`list`を`tuple`に正規化する。

    `resolve_site`（`seqatelier.core.sequence`）は`(start, end)`を`tuple`として
    `isinstance`判定するが、MCP/JSON境界を越えた`(start, end)`はJSON配列
    ——Pythonでは`list`——として届く。ここで1箇所吸収し、`resolve_site`側の
    型判定を変更せずに済ませる。
    """
    if isinstance(site, list):
        if len(site) != 2:
            raise SequenceValidationError(
                f"座標指定のlistは[start, end]の2要素である必要があります（{len(site)}要素が指定されました）。"
            )
        return (site[0], site[1])
    return site


def calc_tm_api(
    sequence: str,
    na_mm: float = 50.0,
    mg_mm: float = 2.0,
    dntp_mm: float = 0.8,
    primer_conc_nm: float = 250.0,
) -> dict[str, Any]:
    """プライマー配列のTmをnearest-neighbor法で計算する。

    戻り値: {"sequence": str, "tm_celsius": float, "gc_percent": float, "length": int}
    """
    params = TmParameters(
        na_mm=na_mm, mg_mm=mg_mm, dntp_mm=dntp_mm, primer_conc_nm=primer_conc_nm
    )
    tm = calc_tm(sequence, params)
    return {
        "sequence": sequence.upper(),
        "tm_celsius": tm,
        "gc_percent": gc_percent(sequence),
        "length": len(sequence),
    }


def infusion_from_files(
    vector_path: str,
    insert_path: str,
    insertion_site: int | tuple[int, int] | list[int] | str,
    construct_name: str = "construct",
    homology_arm_bp: int = 15,
    target_tm: float = 60.0,
) -> dict[str, Any]:
    """`vector_path`・`insert_path`のGenBankファイルからIn-Fusionプライマーを設計する。

    内部で`LabRecord.from_genbank()`を2回呼び、`design_infusion`
    （`seqatelier.primer.infusion`）に渡す。戻り値は`InFusionDesign.to_dict()`。
    """
    vector = LabRecord.from_genbank(vector_path)
    insert = LabRecord.from_genbank(insert_path)
    design = design_infusion(
        vector,
        insert,
        _normalize_site(insertion_site),
        construct_name=construct_name,
        homology_arm_bp=homology_arm_bp,
        target_tm=target_tm,
        annotate_vector=False,
        annotate_insert=False,
    )
    return design.to_dict()


def quikchange_from_file(
    template_path: str,
    site: int | tuple[int, int] | list[int] | str,
    new_sequence: str = "",
    construct_name: str = "mutant",
) -> dict[str, Any]:
    """`template_path`のGenBankファイルからQuikChangeプライマーを設計する。

    内部で`LabRecord.from_genbank()`を呼び、`design_quikchange`
    （`seqatelier.primer.quikchange`）に渡す。戻り値は`QuikChangeDesign.to_dict()`。
    """
    template = LabRecord.from_genbank(template_path)
    design = design_quikchange(
        template,
        _normalize_site(site),
        new_sequence=new_sequence,
        construct_name=construct_name,
        annotate=False,
    )
    return design.to_dict()


def point_mutation_from_file(
    template_path: str,
    residue_number: int,
    new_amino_acid: str,
    host: str = "ecoli_k12",
    cds_feature_label: str | None = None,
    cds_start_bp: int | None = None,
    construct_name: str | None = None,
) -> dict[str, Any]:
    """`template_path`のGenBankファイルから残基番号指定の点変異プライマーを設計する。

    内部で`LabRecord.from_genbank()`を呼び、`design_point_mutation_by_codon`
    （`seqatelier.primer.quikchange`）に渡す。戻り値は`QuikChangeDesign.to_dict()`。
    """
    template = LabRecord.from_genbank(template_path)
    design = design_point_mutation_by_codon(
        template,
        residue_number,
        new_amino_acid,
        host=host,
        cds_feature_label=cds_feature_label,
        cds_start_bp=cds_start_bp,
        construct_name=construct_name,
        annotate=False,
    )
    return design.to_dict()


def optimize_codons_api(
    aa_sequence: str,
    host: str,
    gc_min: float = 40.0,
    gc_max: float = 60.0,
) -> dict[str, Any]:
    """アミノ酸配列を`host`向けにコドン最適化する。

    内部で`optimize_sequence`（`seqatelier.codon.optimize`）を呼ぶ。
    戻り値は`CodonOptimizationResult.to_dict()`。
    """
    result = optimize_sequence(aa_sequence, host, gc_min=gc_min, gc_max=gc_max)
    return result.to_dict()


def linear_map_from_file(
    genbank_path: str,
    region_start: int | None = None,
    region_end: int | None = None,
    line_width: int = 60,
) -> dict[str, Any]:
    """`genbank_path`のGenBankファイルを線形テキストマップとして描画する。

    `region_start`/`region_end`（1-based inclusive）はどちらも指定するか、
    どちらも省略する（省略時はレコード全体を表示）。内部で
    `LabRecord.from_genbank()`を呼び、`render_linear_map`
    （`seqatelier.display.linear_map`）に渡す。戻り値は`LinearMap.to_dict()`。
    """
    if (region_start is None) != (region_end is None):
        raise SequenceValidationError(
            "region_startとregion_endは両方指定するか、両方省略してください。"
        )
    region = (region_start, region_end) if region_start is not None and region_end is not None else None
    record = LabRecord.from_genbank(genbank_path)
    linear_map = render_linear_map(record, region=region, line_width=line_width)
    return linear_map.to_dict()


def search_index(index_path: str, query: str) -> list[dict[str, Any]]:
    """`index_path`のindex.csvを`query`で検索する。

    内部で`search`（`seqatelier.core.index`）を呼ぶ。
    戻り値は`IndexEntry.to_dict()`のリスト。
    """
    entries = search(index_path, query)
    return [entry.to_dict() for entry in entries]


def register_genbank(
    index_path: str,
    genbank_path: str,
    kind: str,
    entry_id: str | None = None,
    description: str = "",
    tags: str = "",
) -> dict[str, Any]:
    """`genbank_path`のGenBankファイルを読み込み、`index_path`のindex.csvに登録する。

    内部で`register_from_genbank`（`seqatelier.core.index`）を呼ぶ。
    戻り値は`IndexEntry.to_dict()`。
    """
    entry = register_from_genbank(
        index_path,
        genbank_path,
        kind,
        entry_id=entry_id,
        description=description,
        tags=tags,
    )
    return entry.to_dict()
