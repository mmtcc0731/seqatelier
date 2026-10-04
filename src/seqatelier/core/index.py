"""配列インデックス（data/index.csv）の管理（WC-4、設計C）。

フラットなCSVをそのままデータベースとして使う: 人間が読める、gitで
diffできる、SeqAtelierを介さずgrepできる、という3点を優先した設計判断
（案C: 実用性最優先）。このモジュールだけがindex.csvを読み書きする、
という原則により、スキーマ（`INDEX_FIELDS`）と失敗モードを一箇所に
集約する。

全ての書き込みはアトミック（同一ディレクトリの一時ファイル+rename）で
行うため、書き込み中のクラッシュでindex.csvが壊れることはない。
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from seqatelier.core.sequence import LabRecord
from seqatelier.core.types import IndexEntry, SequenceIndexError

__all__ = [
    "INDEX_FIELDS",
    "add_entry",
    "list_entries",
    "load_index",
    "register_from_genbank",
    "remove_entry",
    "save_index",
    "search",
]

INDEX_FIELDS: list[str] = ["id", "name", "kind", "path", "length", "description", "tags", "created"]
"""index.csvの列順とIndexEntryのフィールドの単一の正本。"""

_DEFAULT_SEARCH_FIELDS: tuple[str, ...] = ("name", "description", "tags", "id")


def _entry_to_row(entry: IndexEntry) -> dict[str, str]:
    return {
        "id": entry.id,
        "name": entry.name,
        "kind": entry.kind,
        "path": entry.path,
        "length": str(entry.length),
        "description": entry.description,
        "tags": entry.tags,
        "created": entry.created,
    }


def _row_to_entry(row: dict[str, str]) -> IndexEntry:
    try:
        return IndexEntry(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            path=row["path"],
            length=int(row["length"]),
            description=row.get("description", ""),
            tags=row.get("tags", ""),
            created=row.get("created", ""),
        )
    except (KeyError, ValueError) as exc:
        raise SequenceIndexError(f"index.csvの行が不正です: {row!r}（{exc}）。") from exc


def load_index(index_path: str | Path) -> list[IndexEntry]:
    """index.csvから全エントリを読み込む。

    ファイルがまだ無い場合は空リストを返す（新規プロジェクトでは、最初の
    `add_entry`呼び出しまでindex.csvが存在しない）。

    Raises
    ------
    SequenceIndexError
        ファイルは存在するがヘッダーが`INDEX_FIELDS`と一致しない、または
        行のパースに失敗した場合（例: lengthが整数でない）。
    """
    path = Path(index_path)
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or list(reader.fieldnames) != INDEX_FIELDS:
            raise SequenceIndexError(
                f"{path}のヘッダーが{reader.fieldnames!r}でした。期待値は{INDEX_FIELDS!r}です。"
                "ファイルが壊れているか、互換性のないSeqAtelierバージョンで作成された可能性があります。"
            )
        return [_row_to_entry(row) for row in reader]


def save_index(entries: list[IndexEntry], index_path: str | Path) -> None:
    """index.csvを`entries`の内容でまるごと上書きする（アトミック書き込み）。

    カンマを含むdescription/tagsが余分な列と誤読されないよう、全フィールドを
    クォートして書き込む（`csv.QUOTE_ALL`）。
    """
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for entry in entries:
            writer.writerow(_entry_to_row(entry))
    tmp_path.replace(path)


def add_entry(index_path: str | Path, entry: IndexEntry, allow_update: bool = False) -> None:
    """`entry`をindexに追加する（`entry.created`が空なら今日の日付を補完）。

    Raises
    ------
    SequenceIndexError
        `entry.id`が既に存在し、`allow_update=False`（デフォルト）の場合。
    """
    entries = load_index(index_path)
    if not entry.created:
        entry = IndexEntry(
            id=entry.id,
            name=entry.name,
            kind=entry.kind,
            path=entry.path,
            length=entry.length,
            description=entry.description,
            tags=entry.tags,
            created=_dt.date.today().isoformat(),
        )
    existing_idx = next((i for i, e in enumerate(entries) if e.id == entry.id), None)
    if existing_idx is not None:
        if not allow_update:
            raise SequenceIndexError(
                f"id'{entry.id}'は既にindexに存在します。更新する場合はallow_update=Trueを"
                "指定してください。"
            )
        entries[existing_idx] = entry
    else:
        entries.append(entry)
    save_index(entries, index_path)


def remove_entry(index_path: str | Path, entry_id: str) -> bool:
    """`entry_id`に一致するエントリを削除する。削除できれば`True`、無ければ`False`。"""
    entries = load_index(index_path)
    remaining = [e for e in entries if e.id != entry_id]
    if len(remaining) == len(entries):
        return False
    save_index(remaining, index_path)
    return True


def list_entries(index_path: str | Path, kind: str | None = None) -> list[IndexEntry]:
    """全エントリを返す。`kind`を指定した場合はその種類のみに絞る。"""
    entries = load_index(index_path)
    if kind is None:
        return entries
    return [e for e in entries if e.kind == kind]


def search(
    index_path: str | Path,
    query: str,
    fields: tuple[str, ...] = _DEFAULT_SEARCH_FIELDS,
) -> list[IndexEntry]:
    """`query`を`fields`中から部分一致（大文字小文字を無視）で検索する。"""
    needle = query.strip().lower()
    if not needle:
        return []

    def _matches(entry: IndexEntry) -> bool:
        return any(needle in str(getattr(entry, f, "")).lower() for f in fields)

    return [e for e in load_index(index_path) if _matches(e)]


def register_from_genbank(
    index_path: str | Path,
    genbank_path: str | Path,
    kind: str,
    entry_id: str | None = None,
    description: str = "",
    tags: str = "",
    allow_update: bool = False,
) -> IndexEntry:
    """GenBankファイルを読み込み、その基本情報をindexに登録する。"""
    record = LabRecord.from_genbank(genbank_path)
    resolved_id = entry_id or record.name
    entry = IndexEntry(
        id=resolved_id,
        name=record.name,
        kind=kind,
        path=str(Path(genbank_path)),
        length=record.length,
        description=description,
        tags=tags,
        created=_dt.date.today().isoformat(),
    )
    add_entry(index_path, entry, allow_update=allow_update)
    return entry
