"""Packaged Web API, with 0-based half-open coordinates and persistent drafts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from seqatelier import __version__
from seqatelier.auth import AccessControl
from seqatelier.codon.optimize import CODON_USAGE_TABLES, GENETIC_CODE, resolve_host
from seqatelier.core.types import SeqAtelierError
from seqatelier.oauth import OAuthAccessControl, OAuthSettings
from seqatelier.primer.tm import TmParameters, calc_tm, gc_percent
from seqatelier.workspace import ConflictError, Workspace, WorkspaceError


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionInput(Input):
    plasmid_id: str
    expected_revision: str = Field(min_length=1)


class MutateInput(RevisionInput):
    position: StrictInt
    new_codon: str = Field(min_length=3, max_length=3, pattern="^[ACGTacgt]{3}$")


class FeatureInput(Input):
    type: str = Field(min_length=1, max_length=80, pattern="^[A-Za-z][A-Za-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    start: StrictInt
    end: StrictInt
    strand: Literal[1, -1] = 1


class AnnotateInput(RevisionInput):
    action: Literal["add", "update", "delete"]
    index: StrictInt | None = None
    feature: FeatureInput | None = None


class RestoreInput(RevisionInput):
    revision: str


class ImportInput(Input):
    genbank: str = Field(min_length=1, max_length=10 * 1024 * 1024)


class TmInput(Input):
    sequence: str = Field(max_length=10000)
    na_mm: float = Field(default=50.0, ge=0, le=10000, allow_inf_nan=False)
    mg_mm: float = Field(default=2.0, ge=0, le=1000, allow_inf_nan=False)
    dntp_mm: float = Field(default=0.8, ge=0, le=1000, allow_inf_nan=False)
    primer_conc_nm: float = Field(default=250.0, gt=0, le=1e9, allow_inf_nan=False)


class TranslateInput(Input):
    sequence: str = Field(max_length=1_000_000, pattern="^[ACGTRYSWKMBDHVNacgtryswkmbdhvn]*$")
    strand: Literal[1, -1] = 1


def calculate_tm(sequence: str, **kwargs) -> dict[str, Any]:
    seq = sequence.strip().upper()
    result = {"sequence": seq, "length": len(seq), "tm_celsius": None, "gc_percent": None, "error": None}
    try:
        result["gc_percent"] = gc_percent(seq)
        result["tm_celsius"] = calc_tm(seq, TmParameters(**kwargs))
    except SeqAtelierError as exc:
        result["error"] = str(exc)
    return result


def _feature(record, supplied: FeatureInput, base: SeqFeature | None = None) -> SeqFeature:
    if not 0 <= supplied.start < supplied.end <= record.length:
        raise WorkspaceError("Feature coordinates are outside the sequence.")
    location = SimpleLocation(supplied.start, supplied.end, strand=supplied.strand)
    if base is not None and isinstance(base.location, CompoundLocation):
        if (supplied.start, supplied.end, supplied.strand) != (
            int(base.location.start),
            int(base.location.end),
            base.location.strand,
        ):
            raise WorkspaceError(
                "Edit joined feature coordinates through Python; the viewer cannot flatten them."
            )
        location = base.location
    qualifiers = deepcopy(base.qualifiers) if base is not None else {}
    qualifiers["label"] = [supplied.label]
    qualifiers.pop("translation", None)
    return SeqFeature(location, type=supplied.type, qualifiers=qualifiers)


def create_app(
    workspace: Workspace | None = None,
    *,
    token: str | None = None,
    oauth: OAuthSettings | None = None,
    mcp_app=None,
) -> FastAPI:
    ws = workspace or Workspace()

    @asynccontextmanager
    async def lifespan(app):
        if mcp_app is None:
            yield
        else:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield

    app = FastAPI(title="SeqAtelier", version=__version__, lifespan=lifespan)
    if oauth:
        app.add_middleware(OAuthAccessControl, settings=oauth)
    else:
        # Validate the local token at startup, before accepting requests.
        AccessControl(app, token=token)
        app.add_middleware(AccessControl, token=token)

    @app.get("/auth/config")
    def auth_config():
        return {"mode": "local"}

    @app.exception_handler(SeqAtelierError)
    async def domain_error(request: Request, exc: SeqAtelierError):
        return JSONResponse(
            status_code=409 if isinstance(exc, ConflictError) else 400, content={"detail": str(exc)}
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/session")
    def session():
        return {"authenticated": True}

    @app.get("/api/plasmids")
    def list_records(query: str = ""):
        return ws.list_records(query, limit=1000)

    @app.get("/api/plasmid/{record_id}")
    def get_record(record_id: str):
        return ws.get_record(record_id)

    @app.post("/api/import")
    def import_record(req: ImportInput):
        return ws.import_record(req.genbank)

    @app.get("/api/plasmid/{record_id}/history")
    def history(record_id: str):
        return ws.history(record_id)

    @app.get("/api/plasmid/{record_id}/genbank")
    def export(record_id: str):
        return Response(
            ws.export_genbank(record_id),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{record_id}.gb"'},
        )

    @app.post("/api/mutate")
    def mutate(req: MutateInput):
        def change(record):
            if not 0 <= req.position <= record.length - 3:
                raise WorkspaceError("Mutation position is outside the sequence.")
            sequence = record.sequence
            record.record.seq = Seq(
                sequence[: req.position] + req.new_codon.upper() + sequence[req.position + 3 :]
            )
            for feature in record.record.features:
                feature.qualifiers.pop("translation", None)

        return ws.edit(
            req.plasmid_id,
            req.expected_revision,
            change,
            f"Replace bases {req.position + 1}–{req.position + 3}",
        )

    @app.post("/api/annotate")
    def annotate(req: AnnotateInput):
        def change(record):
            if req.action == "add":
                if req.feature is None:
                    raise WorkspaceError("feature is required for add.")
                record.record.features.append(_feature(record, req.feature))
                return
            mapping = [i for i, f in enumerate(record.record.features) if f.location is not None]
            if req.index is None or not 0 <= req.index < len(mapping):
                raise WorkspaceError("Feature index is outside the record.")
            index = mapping[req.index]
            if req.action == "delete":
                del record.record.features[index]
            elif req.feature is None:
                raise WorkspaceError("feature is required for update.")
            else:
                record.record.features[index] = _feature(record, req.feature, record.record.features[index])

        return ws.edit(req.plasmid_id, req.expected_revision, change, f"{req.action.title()} feature")

    @app.post("/api/save")
    def save(req: RevisionInput):
        return ws.save(req.plasmid_id, req.expected_revision)

    @app.post("/api/reload")
    def discard(req: RevisionInput):
        return ws.discard_draft(req.plasmid_id, req.expected_revision)

    @app.post("/api/restore")
    def restore(req: RestoreInput):
        return ws.restore(req.plasmid_id, req.revision, req.expected_revision)

    @app.post("/api/tm")
    def tm(req: TmInput):
        return calculate_tm(**req.model_dump())

    @app.post("/api/translate")
    def translate(req: TranslateInput):
        seq = Seq(req.sequence.upper())
        if req.strand == -1:
            seq = seq.reverse_complement()
        usable = len(seq) - len(seq) % 3
        protein = str(seq[:usable].translate())
        return {
            "protein": protein,
            "length_aa": len(protein),
            "length_nt": usable,
            "strand": req.strand,
            "has_stop": "*" in protein,
            "warning": "Trailing incomplete codon omitted." if usable != len(seq) else None,
        }

    @app.get("/api/hosts")
    def hosts():
        return sorted(CODON_USAGE_TABLES)

    @app.get("/api/codon-table")
    def codon_table(host: str = "ecoli_k12"):
        key = resolve_host(host)
        codons = [
            {"codon": codon, "amino_acid": aa, "frequency": CODON_USAGE_TABLES[key].get(codon, 0)}
            for codon, aa in GENETIC_CODE.items()
        ]
        codons.sort(key=lambda c: (c["amino_acid"], -c["frequency"]))
        return {"host": key, "codons": codons}

    if mcp_app is not None:
        app.router.routes.extend(mcp_app.routes)
    assets = Path(__file__).parent / "web_assets"
    if (assets / "index.html").is_file():
        app.mount("/", StaticFiles(directory=assets, html=True), name="viewer")
    else:

        @app.get("/")
        def missing_assets():
            return JSONResponse(
                status_code=503,
                content={"detail": "Viewer assets missing. Run scripts/build_viewer.py before packaging."},
            )

    return app
