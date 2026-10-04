"""Portable workspaces: immutable GenBank objects and closed SQLite snapshots.

Transactions run in memory; only complete catalogs are atomically published.
Local locks serialize this computer's writers. Folder synchronization and
coordination between computers belong to the user and their sync provider.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from Bio import SeqIO
from filelock import FileLock, Timeout

from seqatelier.core.sequence import LabRecord, as_int
from seqatelier.core.types import SeqAtelierError
from seqatelier.settings import config_path, lock_directory, resolve_workspace

SCHEMA_VERSION = 2
MAX_GENBANK_BYTES = 10 * 1024 * 1024
MAX_SEQUENCE_LENGTH = 1_000_000


class WorkspaceError(SeqAtelierError):
    """Invalid workspace, input or record identifier."""


class ConflictError(WorkspaceError):
    """The record has changed since the caller last read it."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def workspace_path(value: str | Path | None = None) -> Path:
    return resolve_workspace(value).path


def parse_genbank(text: str) -> LabRecord:
    if len(text.encode("utf-8")) > MAX_GENBANK_BYTES:
        raise WorkspaceError("GenBank input exceeds 10 MiB.")
    try:
        record = SeqIO.read(io.StringIO(text), "genbank")
    except (ValueError, TypeError) as exc:
        raise WorkspaceError(f"Expected one valid GenBank record: {exc}") from exc
    result = LabRecord(record)
    if not 0 < result.length <= MAX_SEQUENCE_LENGTH:
        raise WorkspaceError("Sequence length must be between 1 and 1,000,000 bases.")
    if set(result.sequence) - set("ACGTURYSWKMBDHVN"):
        raise WorkspaceError("Sequence contains unsupported nucleotide characters.")
    return result


def genbank_text(record: LabRecord) -> str:
    record.record.annotations.setdefault("molecule_type", "DNA")
    handle = io.StringIO()
    SeqIO.write(record.record, handle, "genbank")
    return handle.getvalue()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".seqatelier-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Workspace:
    def __init__(self, path: str | Path | None = None):
        self.selection = resolve_workspace(path)
        self.path = self.selection.path
        self.database = self.path / "seqatelier.sqlite3"

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        # Keep transient locks outside synchronized data. These do not coordinate PCs.
        key = hashlib.sha256(os.path.normcase(str(self.path)).encode("utf-8")).hexdigest()
        folder = lock_directory()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(folder / f"{key}.lock", timeout=30):
                yield
        except Timeout as exc:
            raise ConflictError(
                "Workspace is busy on this computer. Finish the other operation and retry."
            ) from exc

    def _check_files(self, *, writing: bool) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            if self.database.with_name(self.database.name + suffix).exists():
                raise WorkspaceError(
                    "SQLite journal files are present. Close older app versions and finish synchronization; "
                    "if they remain, recover the original database or restore a backup. Do not delete journals."
                )
        if writing and any(p != self.database for p in self.path.glob("seqatelier*.sqlite3")):
            raise ConflictError(
                "Another workspace catalog is present, possibly a sync conflict copy. "
                "Preserve both copies and resolve the conflict before writing."
            )

    def _load_catalog(self) -> bytes:
        if not self.database.is_file():
            raise WorkspaceError(
                f"Workspace catalog is missing at {self.path}. Check the location and finish downloading/syncing. "
                "For a new workspace, run: seqatelier --workspace PATH init"
            )
        self._check_files(writing=False)
        content = self.database.read_bytes()
        if len(content) < 100 or content[:16] != b"SQLite format 3\x00":
            raise WorkspaceError("Invalid workspace catalog; finish synchronization or restore a backup.")
        # Serialized WAL databases require their sidecars and cannot be reopened in memory.
        if content[18:20] != b"\x01\x01":
            raise WorkspaceError(
                "WAL catalogs are unsupported. Export a backup from the app that created it."
            )
        return content

    @staticmethod
    def _identity(db: sqlite3.Connection) -> str:
        row = db.execute("SELECT value FROM metadata WHERE key='workspace_id'").fetchone()
        if not row or not row[0]:
            raise WorkspaceError("Workspace identity is missing; restore a backup.")
        return row[0]

    def _check_identity(self, db: sqlite3.Connection) -> None:
        identifier = self._identity(db)
        if self.selection.workspace_id and identifier != self.selection.workspace_id:
            raise WorkspaceError(
                "A different workspace is now at the registered path. "
                "Check the folder, then register the intended workspace with 'seqatelier workspace use PATH'."
            )

    def _check_objects(self, db: sqlite3.Connection) -> None:
        for (digest,) in db.execute("SELECT DISTINCT object_hash FROM revisions"):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise WorkspaceError("Invalid object hash in workspace.")
            if not (self.path / "objects" / (digest + ".gb")).is_file():
                raise WorkspaceError(
                    "Some sequence files are missing. Make the whole workspace available offline "
                    "and finish synchronization before writing."
                )

    def _publish(self, db: sqlite3.Connection, original: bytes | None) -> None:
        self._check_files(writing=True)
        current = self.database.read_bytes() if self.database.exists() else None
        if current != original:
            raise ConflictError(
                "Workspace changed outside this app while saving. Finish synchronization, then read and retry."
            )
        atomic_write(self.database, db.serialize())

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._write_lock() if write else nullcontext():
            original = self._load_catalog()
            with closing(sqlite3.connect(":memory:")) as db:
                try:
                    db.deserialize(original)
                    db.row_factory = sqlite3.Row
                    db.execute("PRAGMA foreign_keys=ON")
                    if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                        raise WorkspaceError(
                            "Unsupported workspace schema. For a 0.2 preview workspace, back it up "
                            "and run 'seqatelier --workspace PATH init' to upgrade."
                        )
                    self._check_identity(db)
                    if write:
                        self._check_files(writing=True)
                        self._check_objects(db)
                        db.execute("BEGIN IMMEDIATE")
                    yield db
                    db.commit()
                    if write:
                        self._publish(db, original)
                except sqlite3.DatabaseError as exc:
                    raise WorkspaceError(f"Workspace catalog cannot be read: {exc}") from exc

    def initialize(self) -> dict[str, Any]:
        if self.selection.workspace_id and not self.database.is_file():
            raise WorkspaceError(
                "The registered workspace is missing. Check its path or finish synchronization; "
                "a replacement workspace will not be created automatically."
            )
        self.path.mkdir(parents=True, exist_ok=True)
        with self._write_lock(), closing(sqlite3.connect(":memory:")) as db:
            self._check_files(writing=True)
            original = self._load_catalog() if self.database.exists() else None
            if original is not None:
                db.deserialize(original)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if self.selection.workspace_id and version != SCHEMA_VERSION:
                raise WorkspaceError(
                    "Registered workspace identity cannot be verified; check the folder and version."
                )
            if version == SCHEMA_VERSION:
                self._check_identity(db)
                return self.info()
            if version == 1:
                self._check_objects(db)
                self._add_identity(db)
                db.commit()
                self._publish(db, original)
                return self.info()
            if version != 0 or db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise WorkspaceError("Existing database is not a compatible workspace.")
            schema = """
                CREATE TABLE records (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    description TEXT NOT NULL, created TEXT NOT NULL,
                    head TEXT NOT NULL, draft TEXT
                );
                CREATE TABLE revisions (
                    id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                    object_hash TEXT NOT NULL, parent TEXT, created TEXT NOT NULL,
                    message TEXT NOT NULL, saved INTEGER NOT NULL
                );
                CREATE INDEX revisions_by_record ON revisions(record_id, created);
                CREATE TABLE designs (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL
                );
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            self._add_identity(db)
            db.commit()
            self._publish(db, original)
        return self.info()

    @staticmethod
    def _add_identity(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO metadata VALUES ('workspace_id', ?)", (str(uuid.uuid4()),))
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def use(self) -> dict[str, Any]:
        """Register an existing folder on this computer, including its stable identity."""
        result = self.info()
        config = {"version": 1, "workspace": {"path": str(self.path), "id": result["workspace_id"]}}
        atomic_write(config_path(), (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return {**result, "configuration": str(config_path())}

    def info(self) -> dict[str, Any]:
        with self._connect() as db:
            return {
                "workspace": str(self.path),
                "workspace_id": self._identity(db),
                "location_source": self.selection.source,
                "schema_version": SCHEMA_VERSION,
                "records": db.execute("SELECT COUNT(*) FROM records").fetchone()[0],
                "designs": db.execute("SELECT COUNT(*) FROM designs").fetchone()[0],
            }

    def _put_object(self, record: LabRecord) -> str:
        text = genbank_text(record)
        parse_genbank(text)
        content = text.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        target = self.path / "objects" / (digest + ".gb")
        if not target.exists():
            atomic_write(target, content)
        return digest

    def _read_object(self, digest: str) -> LabRecord:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise WorkspaceError("Invalid object hash in workspace.")
        try:
            content = (self.path / "objects" / (digest + ".gb")).read_bytes()
        except FileNotFoundError as exc:
            raise WorkspaceError(
                "Sequence file is missing. Make the whole workspace available offline and finish synchronization."
            ) from exc
        if hashlib.sha256(content).hexdigest() != digest:
            raise WorkspaceError("GenBank object checksum mismatch; restore it from a backup.")
        return parse_genbank(content.decode("utf-8"))

    def _state(self, db: sqlite3.Connection, record_id: str) -> dict[str, Any]:
        row = db.execute(
            """
            SELECT r.*, v.id AS revision, v.object_hash
            FROM records r JOIN revisions v ON v.id = COALESCE(r.draft,r.head)
            WHERE r.id=?
        """,
            (record_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceError(f"Unknown record ID: {record_id}")
        return dict(row)

    @staticmethod
    def _check_revision(state: dict[str, Any], expected_revision: str) -> None:
        if not expected_revision or state["revision"] != expected_revision:
            raise ConflictError("Record changed. Read it again and review the changes before retrying.")

    def import_record(
        self, text: str, *, record_id: str | None = None, name: str | None = None, kind: str = "plasmid"
    ) -> dict[str, Any]:
        record = parse_genbank(text)
        identifier = record_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier):
            raise WorkspaceError(
                "Record ID must use 1–128 ASCII letters, digits, dots, underscores or hyphens."
            )
        if kind not in {"plasmid", "fragment", "primer"}:
            raise WorkspaceError("kind must be plasmid, fragment or primer.")
        revision = uuid.uuid4().hex
        now = utc_now()
        with self._connect(write=True) as db:
            if db.execute("SELECT 1 FROM records WHERE id=?", (identifier,)).fetchone():
                raise ConflictError(f"Record ID already exists: {identifier}")
            digest = self._put_object(record)
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,NULL)",
                (identifier, name or record.name, kind, record.record.description, now, revision),
            )
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,1)",
                (revision, identifier, digest, None, now, "Imported GenBank"),
            )
        return self.get_record(identifier)

    def load_record(self, record_id: str) -> tuple[dict[str, Any], LabRecord]:
        with self._connect() as db:
            state = self._state(db, record_id)
        return state, self._read_object(state["object_hash"])

    def get_record(self, record_id: str, *, include_sequence: bool = True) -> dict[str, Any]:
        state, record = self.load_record(record_id)
        colors = {
            "CDS": "#4CAF50",
            "promoter": "#FF9800",
            "primer_bind": "#9C27B0",
            "primer": "#9C27B0",
            "rep_origin": "#607D8B",
            "polyA_signal": "#795548",
        }
        features = []
        for raw, feature in zip(
            (f for f in record.record.features if f.location is not None), record.features_typed, strict=True
        ):
            assert raw.location is not None
            translation = None
            offset = 0
            if raw.type == "CDS":
                coding = raw.extract(record.record.seq)
                try:
                    offset = int(raw.qualifiers.get("codon_start", ["1"])[0]) - 1
                    if offset in (0, 1, 2) and len(coding) > offset and (len(coding) - offset) % 3 == 0:
                        translation = str(
                            coding[offset:].translate(table=raw.qualifiers.get("transl_table", ["1"])[0])
                        )
                except (ValueError, KeyError):
                    translation = None
            features.append(
                {
                    "type": raw.type,
                    "label": feature.label,
                    "start": feature.location.start,
                    "end": feature.location.end,
                    "strand": feature.location.strand,
                    "translation": translation,
                    "codon_start": offset + 1,
                    "color": colors.get(raw.type, "#2196F3"),
                    "parts": [
                        {"start": as_int(p.start), "end": as_int(p.end), "strand": p.strand}
                        for p in raw.location.parts
                    ],
                }
            )
        result = self._record_summary(state, record)
        result["features"] = features
        if include_sequence:
            result["sequence"] = record.sequence
        return result

    @staticmethod
    def _record_summary(state: dict[str, Any], record: LabRecord) -> dict[str, Any]:
        return {
            "id": state["id"],
            "name": state["name"],
            "kind": state["kind"],
            "description": state["description"],
            "created": state["created"],
            "length": record.length,
            "topology": "circular" if record.is_circular else "linear",
            "revision": state["revision"],
            "saved_revision": state["head"],
            "dirty": state["draft"] is not None,
        }

    def list_records(self, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise WorkspaceError("limit must be between 1 and 1000.")
        with self._connect() as db:
            rows = db.execute("SELECT id,name,description FROM records ORDER BY name,id").fetchall()
            needle = query.casefold()
            ids = [r["id"] for r in rows if needle in " ".join(r).casefold()][:limit]
            states = [self._state(db, identifier) for identifier in ids]
        return [self._record_summary(state, self._read_object(state["object_hash"])) for state in states]

    def edit(
        self, record_id: str, expected_revision: str, change: Callable[[LabRecord], None], message: str
    ) -> dict[str, Any]:
        with self._connect(write=True) as db:
            state = self._state(db, record_id)
            self._check_revision(state, expected_revision)
            record = self._read_object(state["object_hash"])
            change(record)
            digest = self._put_object(record)
            revision = uuid.uuid4().hex
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,0)",
                (revision, record_id, digest, state["revision"], utc_now(), message),
            )
            db.execute("UPDATE records SET draft=? WHERE id=?", (revision, record_id))
        return self.get_record(record_id)

    def save(self, record_id: str, expected_revision: str) -> dict[str, Any]:
        with self._connect(write=True) as db:
            state = self._state(db, record_id)
            self._check_revision(state, expected_revision)
            length = self._read_object(state["object_hash"]).length
            if state["draft"] is not None:
                db.execute("UPDATE revisions SET saved=1 WHERE id=?", (state["draft"],))
                db.execute("UPDATE records SET head=draft,draft=NULL WHERE id=?", (record_id,))
        return {
            "plasmid_id": record_id,
            "revision": state["revision"],
            "length": length,
            "saved": True,
            "path": f"workspace:{record_id}",
        }

    def discard_draft(self, record_id: str, expected_revision: str) -> dict[str, Any]:
        with self._connect(write=True) as db:
            state = self._state(db, record_id)
            self._check_revision(state, expected_revision)
            db.execute("UPDATE records SET draft=NULL WHERE id=?", (record_id,))
        return self.get_record(record_id)

    def history(self, record_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._state(db, record_id)
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id AS revision,parent,created,message,saved FROM revisions WHERE record_id=? ORDER BY rowid DESC",
                    (record_id,),
                )
            ]

    def restore(self, record_id: str, revision: str, expected_revision: str) -> dict[str, Any]:
        with self._connect(write=True) as db:
            state = self._state(db, record_id)
            self._check_revision(state, expected_revision)
            target = db.execute(
                "SELECT object_hash FROM revisions WHERE id=? AND record_id=?", (revision, record_id)
            ).fetchone()
            if target is None:
                raise WorkspaceError("Revision does not belong to this record.")
            self._read_object(target["object_hash"])
            new_revision = uuid.uuid4().hex
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,1)",
                (
                    new_revision,
                    record_id,
                    target["object_hash"],
                    state["revision"],
                    utc_now(),
                    f"Restored {revision}",
                ),
            )
            db.execute("UPDATE records SET head=?,draft=NULL WHERE id=?", (new_revision, record_id))
        return self.get_record(record_id)

    def export_genbank(self, record_id: str) -> str:
        _, record = self.load_record(record_id)
        return genbank_text(record)

    def store_design(self, payload: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
        identifier = uuid.uuid4().hex
        result = {**payload, "id": identifier, "created": utc_now(), "source_revisions": sources}
        with self._connect(write=True) as db:
            for record_id, revision in sources.items():
                self._check_revision(self._state(db, record_id), revision)
            db.execute(
                "INSERT INTO designs VALUES (?,?,?)",
                (identifier, result["created"], json.dumps(result, ensure_ascii=False)),
            )
        return result

    def get_design(self, design_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM designs WHERE id=?", (design_id,)).fetchone()
        if row is None:
            raise WorkspaceError(f"Unknown design ID: {design_id}")
        return json.loads(row["payload"])

    def list_designs(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT id,created,payload FROM designs ORDER BY created DESC").fetchall()
        return [
            {
                "id": r["id"],
                "created": r["created"],
                "name": json.loads(r["payload"])["name"],
                "method": json.loads(r["payload"])["method"],
            }
            for r in rows
        ]

    def backup(self, destination: str | Path) -> Path:
        """Consistent database snapshot plus immutable objects; never overwrite a backup."""
        import zipfile

        target = Path(destination).resolve()
        if target == self.path or self.path in target.parents:
            raise WorkspaceError("Place backups outside the workspace.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "seqatelier.sqlite3"
            with self._connect() as source, closing(sqlite3.connect(snapshot)) as dest:
                source.backup(dest)
                hashes = [r[0] for r in dest.execute("SELECT DISTINCT object_hash FROM revisions")]
            for digest in hashes:
                self._read_object(digest)
            with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "seqatelier.sqlite3")
                for digest in hashes:
                    archive.write(self.path / "objects" / (digest + ".gb"), f"objects/{digest}.gb")
        return target
