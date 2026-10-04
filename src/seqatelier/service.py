"""The same reproducible design operations for CLI, MCP and HTTP callers."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

from seqatelier import __version__
from seqatelier.codon.optimize import optimize_sequence
from seqatelier.core.orders import from_infusion_design, from_quikchange_design
from seqatelier.primer.infusion import design_infusion
from seqatelier.primer.quikchange import design_point_mutation_by_codon, design_quikchange
from seqatelier.workspace import ConflictError, Workspace, WorkspaceError

_FIELDS = {
    "infusion": {
        "vector_id",
        "insert_id",
        "feature_label",
        "start_bp",
        "end_bp",
        "insertion_after_bp",
        "homology_arm_bp",
        "target_tm",
    },
    "quikchange": {"template_id", "feature_label", "start_bp", "end_bp", "insertion_after_bp", "replacement"},
    "point_mutation": {"template_id", "cds_feature_label", "residue_number", "new_amino_acid", "host"},
    "codon_optimization": {"aa_sequence", "host", "gc_min", "gc_max"},
}


def _site(params: dict[str, Any]) -> str | tuple[int, int] | int:
    feature = params.get("feature_label")
    insertion = params.get("insertion_after_bp")
    start, end = params.get("start_bp"), params.get("end_bp")
    if sum([feature is not None, insertion is not None, start is not None or end is not None]) != 1:
        raise WorkspaceError(
            "Choose exactly one site: feature_label, start_bp/end_bp, or insertion_after_bp."
        )
    if feature is not None:
        if not isinstance(feature, str) or not feature.strip():
            raise WorkspaceError("feature_label must be a non-empty string.")
        return feature
    if insertion is not None:
        if type(insertion) is not int or insertion < 0:
            raise WorkspaceError(
                "insertion_after_bp must be an integer >= 0 (0 means before the first base)."
            )
        return insertion
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        raise WorkspaceError("start_bp/end_bp must be 1-based inclusive integers with start_bp <= end_bp.")
    return start, end


def preview_design(
    workspace: Workspace, method: str, parameters: dict[str, Any], name: str = "design"
) -> dict[str, Any]:
    if method not in _FIELDS:
        raise WorkspaceError(f"Unknown design method: {method}")
    unknown = set(parameters) - _FIELDS[method]
    if unknown:
        raise WorkspaceError(f"Unknown parameters: {sorted(unknown)}")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise WorkspaceError("Design name must contain 1–120 characters.")
    sources: dict[str, str] = {}

    def load(key: str):
        identifier = parameters.get(key)
        if not isinstance(identifier, str):
            raise WorkspaceError(f"{key} is required.")
        state, record = workspace.load_record(identifier)
        if identifier in sources and sources[identifier] != state["revision"]:
            raise ConflictError("The same source changed during preview. Read it again and retry the preview.")
        sources[identifier] = state["revision"]
        return record

    def number(key: str, default: float) -> float:
        value = parameters.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise WorkspaceError(f"{key} must be a finite number.")
        return float(value)

    order = None
    if method == "infusion":
        arm = parameters.get("homology_arm_bp", 15)
        if type(arm) is not int or not 10 <= arm <= 100:
            raise WorkspaceError("homology_arm_bp must be an integer from 10 to 100.")
        vector, insert = load("vector_id"), load("insert_id")
        design = design_infusion(
            vector,
            insert,
            _site(parameters),
            construct_name=name,
            homology_arm_bp=arm,
            target_tm=number("target_tm", 60),
            annotate_vector=False,
            annotate_insert=False,
        )
        result = design.to_dict()
        order = from_infusion_design(design, name=name, target_plasmid_id=parameters["vector_id"]).to_dict()
    elif method == "quikchange":
        replacement = parameters.get("replacement", "")
        if (
            not isinstance(replacement, str)
            or len(replacement) > 500
            or set(replacement.upper()) - set("ACGT")
        ):
            raise WorkspaceError("replacement must contain up to 500 ACGT bases.")
        qc = design_quikchange(
            load("template_id"),
            _site(parameters),
            new_sequence=replacement,
            construct_name=name,
            annotate=False,
        )
        result = qc.to_dict()
        order = from_quikchange_design(qc, name=name, target_plasmid_id=parameters["template_id"]).to_dict()
    elif method == "point_mutation":
        residue = parameters.get("residue_number")
        aa = parameters.get("new_amino_acid")
        label = parameters.get("cds_feature_label")
        if type(residue) is not int or not isinstance(aa, str) or not isinstance(label, str):
            raise WorkspaceError("residue_number, new_amino_acid and cds_feature_label are required.")
        qc = design_point_mutation_by_codon(
            load("template_id"),
            residue,
            aa,
            cds_feature_label=label,
            host=parameters.get("host", "human"),
            construct_name=name,
            annotate=False,
        )
        result = qc.to_dict()
        order = from_quikchange_design(qc, name=name, target_plasmid_id=parameters["template_id"]).to_dict()
    else:
        aa = parameters.get("aa_sequence")
        if not isinstance(aa, str) or not 1 <= len(aa) <= 5000:
            raise WorkspaceError("aa_sequence must contain 1–5000 amino acids.")
        result = optimize_sequence(
            aa, parameters.get("host", "human"), gc_min=number("gc_min", 40), gc_max=number("gc_max", 60)
        ).to_dict()
    return {
        "name": name,
        "method": method,
        "parameters": parameters,
        "seqatelier_version": __version__,
        "source_revisions": sources,
        "result": result,
        "order": order,
    }


def save_design(
    workspace: Workspace,
    method: str,
    parameters: dict[str, Any],
    expected_revisions: dict[str, str],
    name: str = "design",
) -> dict[str, Any]:
    preview = preview_design(workspace, method, parameters, name)
    if preview["source_revisions"] != expected_revisions:
        raise ConflictError(
            "Source revisions changed or were omitted. Preview the design again before saving."
        )
    return workspace.store_design(preview, expected_revisions)


def order_csv(design: dict[str, Any]) -> str:
    if not design.get("order"):
        raise WorkspaceError("This design does not contain a primer order.")
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["primer_name", "sequence"])
    for primer in design["order"]["primers"]:
        # Prevent spreadsheet formulas in user-chosen primer names.
        name = primer["name"]
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow([name, primer["sequence"]])
    return out.getvalue()
