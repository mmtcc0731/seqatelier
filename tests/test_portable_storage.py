"""Local folder portability and incomplete/conflicting sync simulation, not a sync service test."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from Bio.Seq import Seq

from seqatelier.cli import main
from seqatelier.demo import initialize_demo
from seqatelier.settings import config_path, resolve_workspace
from seqatelier.workspace import ConflictError, Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path):
    result = Workspace(tmp_path / "Dropbox" / "配列 データ")
    initialize_demo(result)
    return result


def test_registered_folder_moves_and_keeps_identity(ws, tmp_path):
    original = ws.use()
    assert Workspace().info()["workspace_id"] == original["workspace_id"]
    assert resolve_workspace().source == "configuration"
    other_pc = tmp_path / "different-computer" / "Sync Folder"
    shutil.copytree(ws.path, other_pc)
    ws.path.rename(ws.path.with_name("moved"))
    with pytest.raises(WorkspaceError, match="missing"):
        Workspace().initialize()
    assert not ws.path.exists()  # Do not silently replace a disconnected sync folder.
    selected = Workspace(other_pc).use()
    assert selected["workspace_id"] == original["workspace_id"]
    assert Workspace().get_record("demo-vector")["sequence"]
    assert str(ws.path).encode() not in Workspace(other_pc).database.read_bytes()


def test_registered_path_replaced_with_other_workspace_is_rejected(ws, tmp_path):
    ws.use()
    other = Workspace(tmp_path / "other")
    other.initialize()
    shutil.copyfile(other.database, ws.database)
    with pytest.raises(WorkspaceError, match="different workspace"):
        Workspace().info()
    with pytest.raises(WorkspaceError, match="different workspace"):
        Workspace().initialize()
    with closing(sqlite3.connect(":memory:")) as old:
        old.deserialize(ws.database.read_bytes())
        old.execute("DROP TABLE metadata")
        old.execute("PRAGMA user_version=1")
        old.commit()
        ws.database.write_bytes(old.serialize())
    before = ws.database.read_bytes()
    with pytest.raises(WorkspaceError, match="identity cannot be verified"):
        Workspace().initialize()
    assert ws.database.read_bytes() == before


def test_selection_priority_and_cli_repair(ws, tmp_path, monkeypatch, capsys):
    ws.use()
    explicit, environment = tmp_path / "explicit", tmp_path / "environment"
    monkeypatch.setenv("SEQATELIER_WORKSPACE", str(environment))
    assert resolve_workspace().path == environment.resolve()
    assert resolve_workspace(explicit).path == explicit.resolve()
    monkeypatch.delenv("SEQATELIER_WORKSPACE")
    config_path().write_text("broken", encoding="utf-8")
    assert main(["workspace", "show"]) == 2
    assert "Invalid local configuration" in capsys.readouterr().err
    assert main(["workspace", "use", str(ws.path)]) == 0
    assert json.loads(capsys.readouterr().out)["workspace_id"] == ws.info()["workspace_id"]
    assert main(["workspace", "show"]) == 0
    assert json.loads(capsys.readouterr().out)["location_source"] == "configuration"
    ws.database.unlink()
    assert main(["doctor"]) == 2
    assert "missing" in capsys.readouterr().err


def test_catalog_not_modified_until_transaction_finishes(ws):
    original = ws.database.read_bytes()
    with ws._connect(write=True) as db:
        db.execute("UPDATE records SET description='Changed' WHERE id='demo-vector'")
        assert ws.database.read_bytes() == original
        assert not list(ws.path.glob("*.sqlite3-*"))
        assert Workspace(ws.path).get_record("demo-vector")["description"] != "Changed"
    assert Workspace(ws.path).get_record("demo-vector")["description"] == "Changed"
    assert not list(ws.path.glob("*.sqlite3-*"))


def test_failed_edit_does_not_publish_partial_catalog(ws):
    original = ws.database.read_bytes()
    with pytest.raises(ValueError, match="interrupted"), ws._connect(write=True) as db:
        db.execute("DELETE FROM designs")
        db.execute("UPDATE records SET description='Bad'")
        raise ValueError("interrupted")
    assert ws.database.read_bytes() == original


def test_incoming_catalog_change_during_write_is_preserved(ws):
    original = ws.database.read_bytes()
    with closing(sqlite3.connect(":memory:")) as incoming:
        incoming.deserialize(original)
        incoming.execute("UPDATE records SET description='Incoming'")
        incoming.commit()
        received = incoming.serialize()
    with pytest.raises(ConflictError, match="outside this app"), ws._connect(write=True) as db:
        db.execute("UPDATE records SET description='Local'")
        ws.database.write_bytes(received)  # Simulate a sync client replacing the catalog.
    assert ws.database.read_bytes() == received


def test_missing_object_blocks_writes_and_reports_incomplete_download(ws):
    state, _ = ws.load_record("demo-vector")
    (ws.path / "objects" / (state["object_hash"] + ".gb")).unlink()
    with pytest.raises(WorkspaceError, match="offline"):
        ws.get_record("demo-vector")
    original = ws.database.read_bytes()
    with pytest.raises(WorkspaceError, match="missing"):
        ws.import_record(ws.export_genbank("demo-insert"), record_id="another")
    assert ws.database.read_bytes() == original


def test_conflicted_copy_blocks_writes_but_allows_read_and_backup(ws, tmp_path):
    conflict = ws.path / "seqatelier (computer's conflicted copy).sqlite3"
    shutil.copyfile(ws.database, conflict)
    original = ws.get_record("demo-vector")
    with pytest.raises(ConflictError, match="conflict copy"):
        ws.save(original["id"], original["revision"])
    assert ws.get_record("demo-vector") == original
    assert ws.backup(tmp_path / "preserved.zip").is_file()
    assert conflict.is_file()


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_legacy_journals_are_not_ignored(ws, suffix):
    journal = ws.database.with_name(ws.database.name + suffix)
    journal.write_bytes(b"legacy")
    with pytest.raises(WorkspaceError, match="Do not delete journals"):
        ws.info()
    with pytest.raises(WorkspaceError, match="journal"):
        ws.initialize()
    assert journal.read_bytes() == b"legacy"


def test_upgrade_preview_schema_preserves_history(ws):
    original = ws.get_record("demo-vector")
    # Build a closed copy of the previous preview's schema.
    with closing(sqlite3.connect(":memory:")) as old:
        old.deserialize(ws.database.read_bytes())
        old.execute("DROP TABLE metadata")
        old.execute("PRAGMA user_version=1")
        old.commit()
        ws.database.write_bytes(old.serialize())
    with pytest.raises(WorkspaceError, match="upgrade"):
        ws.info()
    upgraded = ws.initialize()
    assert upgraded["schema_version"] == 2 and upgraded["workspace_id"]
    assert ws.get_record("demo-vector") == original
    assert ws.initialize()["workspace_id"] == upgraded["workspace_id"]


def test_separate_process_writers_keep_both_imports(ws):
    source = ws.path.parent / "source.gb"
    source.write_text(ws.export_genbank("demo-vector"), encoding="utf-8")

    def run(identifier):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "seqatelier",
                "--workspace",
                str(ws.path),
                "import",
                str(source),
                "--id",
                identifier,
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["first", "second"]))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    assert ws.info()["records"] == 4
    record = ws.get_record("first")
    ws.edit(
        "first", record["revision"], lambda r: setattr(r.record, "seq", Seq("AAA" + r.sequence[3:])), "Edit"
    )
    assert len(ws.history("first")) == 2
