"""Persistence, provenance and competing-client regressions on synthetic data."""

import csv
import io
import json
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from Bio.Seq import Seq

from seqatelier.demo import initialize_demo
from seqatelier.service import order_csv, preview_design, save_design
from seqatelier.workspace import ConflictError, Workspace, WorkspaceError


@pytest.fixture
def workspace(tmp_path):
    ws = Workspace(tmp_path / "workspace")
    initialize_demo(ws)
    return ws


def mutate(record):
    record.record.seq = Seq("AAA" + record.sequence[3:])


def test_restart_save_discard_restore_and_backup(workspace, tmp_path):
    original = workspace.get_record("demo-vector")
    edited = workspace.edit(original["id"], original["revision"], mutate, "Synthetic edit")
    reopened = Workspace(workspace.path)
    assert reopened.get_record(original["id"]) == edited
    assert edited["dirty"] and edited["sequence"].startswith("AAA")
    assert len(reopened.history(original["id"])) == 2
    with pytest.raises(ConflictError):
        reopened.save(original["id"], original["revision"])
    saved = reopened.save(edited["id"], edited["revision"])
    assert saved["revision"] == edited["revision"]
    restored = reopened.restore(original["id"], original["revision"], edited["revision"])
    assert restored["sequence"] == original["sequence"]
    assert restored["revision"] != original["revision"] and not restored["dirty"]
    draft = reopened.edit(original["id"], restored["revision"], mutate, "Second edit")
    discarded = reopened.discard_draft(original["id"], draft["revision"])
    assert discarded["revision"] == restored["revision"]
    assert draft["revision"] in {r["revision"] for r in reopened.history(original["id"])}
    backup = reopened.backup(tmp_path / "backup.zip")
    with pytest.raises(FileExistsError):
        reopened.backup(backup)
    with zipfile.ZipFile(backup) as archive:
        archive.extractall(tmp_path / "restored")
    recovered = Workspace(tmp_path / "restored")
    assert recovered.get_record(original["id"]) == discarded
    assert recovered.history(original["id"]) == reopened.history(original["id"])


def test_competing_writers_only_one_succeeds(workspace):
    revision = workspace.get_record("demo-vector")["revision"]

    def edit():
        try:
            Workspace(workspace.path).edit("demo-vector", revision, mutate, "Concurrent edit")
            return "saved"
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: edit(), range(2))) == ["conflict", "saved"]
    assert len(workspace.history("demo-vector")) == 2


def test_concurrent_initialization(tmp_path):
    path = tmp_path / "new"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Workspace(path).initialize(), range(2)))
    assert all(result["records"] == 0 for result in results)


def test_import_never_overwrites_and_checks_paths(workspace):
    text = workspace.export_genbank("demo-vector")
    with pytest.raises(ConflictError):
        workspace.import_record(text, record_id="demo-vector")
    with pytest.raises(WorkspaceError):
        workspace.import_record(text, record_id="../../outside")
    with pytest.raises(WorkspaceError):
        workspace.import_record(text + text)
    assert workspace.info()["records"] == 2


def test_corruption_detected_without_creating_backup(workspace, tmp_path):
    state, _ = workspace.load_record("demo-vector")
    path = workspace.path / "objects" / (state["object_hash"] + ".gb")
    path.write_text("corrupt", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="checksum"):
        workspace.get_record("demo-vector")
    backup = tmp_path / "bad.zip"
    with pytest.raises(WorkspaceError, match="checksum"):
        workspace.backup(backup)
    assert not backup.exists()


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("infusion", {"vector_id": "demo-vector", "insert_id": "demo-insert", "insertion_after_bp": 100}),
        ("quikchange", {"template_id": "demo-vector", "start_bp": 301, "end_bp": 303, "replacement": "GCT"}),
        (
            "point_mutation",
            {
                "template_id": "demo-vector",
                "cds_feature_label": "demo_CDS",
                "residue_number": 2,
                "new_amino_acid": "R",
            },
        ),
        ("codon_optimization", {"aa_sequence": "MAGWEL", "host": "human"}),
    ],
)
def test_preview_and_save_provenance(workspace, method, params):
    before = workspace.export_genbank("demo-vector")
    preview = preview_design(workspace, method, params, "=synthetic")
    assert workspace.info()["designs"] == 0
    assert workspace.export_genbank("demo-vector") == before
    saved = save_design(workspace, method, params, preview["source_revisions"], "=synthetic")
    assert workspace.get_design(saved["id"]) == saved
    if saved["order"]:
        rows = list(csv.DictReader(io.StringIO(order_csv(saved))))
        assert all(row["primer_name"].startswith("'=") for row in rows)
        assert all(set(row["sequence"]) <= set("ACGT") for row in rows)
    if preview["source_revisions"]:
        revision = workspace.get_record("demo-vector")["revision"]
        workspace.edit("demo-vector", revision, mutate, "New source")
        with pytest.raises(ConflictError):
            save_design(workspace, method, params, preview["source_revisions"])
        assert workspace.info()["designs"] == 1


def test_cli_from_other_directory_and_json_stdout(tmp_path):
    ws = tmp_path / "data"
    command = [sys.executable, "-m", "seqatelier", "--workspace", str(ws)]
    initialized = subprocess.run(
        [*command, "init", "--demo"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert json.loads(initialized.stdout)["records"] == 2
    listed = subprocess.run(
        [*command, "list", "demo"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert len(json.loads(listed.stdout)) == 2
    bad = subprocess.run(
        [*command, "export", "unknown", str(tmp_path / "missing.gb")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2 and json.loads(bad.stderr)["type"] == "WorkspaceError"
    assert not (tmp_path / "missing.gb").exists()


def test_same_record_cannot_mix_revisions_during_preview(workspace, monkeypatch):
    original_load = workspace.load_record
    first_read = True

    def concurrently_changed(identifier):
        nonlocal first_read
        state, record = original_load(identifier)
        if first_read:
            first_read = False
            workspace.edit(identifier, state["revision"], mutate, "Concurrent source edit")
        return state, record

    monkeypatch.setattr(workspace, "load_record", concurrently_changed)
    with pytest.raises(ConflictError, match="during preview"):
        preview_design(workspace, "infusion", {"vector_id": "demo-vector", "insert_id": "demo-vector",
                                               "insertion_after_bp": 100})
    assert workspace.info()["designs"] == 0
