"""配列インデックス index.csv（A-08）のテスト。

追加・検索・削除・重複ID処理・CSVクォーティング規約・GenBankからの直接登録
（`register_from_genbank`）が正しく動作することを検証する。
"""

from __future__ import annotations

import csv

import pytest

from seqatelier.core.index import add_entry, load_index, register_from_genbank, remove_entry, search
from seqatelier.core.types import IndexEntry, SequenceIndexError


def _entry(entry_id: str, name: str = "test", description: str = "", tags: str = "") -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        name=name,
        kind="plasmid",
        path=f"/tmp/{entry_id}.gb",
        length=100,
        description=description,
        tags=tags,
    )


def test_add_and_load(tmp_index_path):
    add_entry(tmp_index_path, _entry("vec1", name="pTestVec"))

    entries = load_index(tmp_index_path)
    assert len(entries) == 1
    assert entries[0].id == "vec1"
    assert entries[0].name == "pTestVec"
    assert entries[0].created  # 未指定なら今日の日付が自動補完される


def test_search(tmp_index_path):
    add_entry(tmp_index_path, _entry("vec1", name="pTestVec", description="GFP expression vector"))
    add_entry(
        tmp_index_path, _entry("vec2", name="pOtherVec", description="mCherry expression vector")
    )

    gfp_results = search(tmp_index_path, "GFP")
    assert len(gfp_results) == 1
    assert gfp_results[0].id == "vec1"

    all_results = search(tmp_index_path, "expression")
    assert len(all_results) == 2

    no_results = search(tmp_index_path, "nonexistent_query")
    assert no_results == []


def test_duplicate_id_raises(tmp_index_path):
    add_entry(tmp_index_path, _entry("vec1"))
    with pytest.raises(SequenceIndexError):
        add_entry(tmp_index_path, _entry("vec1"))


def test_duplicate_id_allow_update(tmp_index_path):
    add_entry(tmp_index_path, _entry("vec1", description="original"))
    add_entry(tmp_index_path, _entry("vec1", description="updated"), allow_update=True)

    entries = load_index(tmp_index_path)
    assert len(entries) == 1
    assert entries[0].description == "updated"


def test_remove(tmp_index_path):
    add_entry(tmp_index_path, _entry("vec1"))
    add_entry(tmp_index_path, _entry("vec2"))

    assert remove_entry(tmp_index_path, "vec1") is True
    entries = load_index(tmp_index_path)
    assert len(entries) == 1
    assert entries[0].id == "vec2"

    assert remove_entry(tmp_index_path, "nonexistent") is False


def test_csv_quoting(tmp_index_path):
    tricky_description = 'contains, a comma and "quotes" too'
    add_entry(
        tmp_index_path, _entry("vec1", description=tricky_description, tags="tag1,tag2,tag3")
    )

    # csv.QUOTE_ALLで書かれているため、生のCSVとして読んでも壊れていないこと
    with open(tmp_index_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["description"] == tricky_description
    assert rows[0]["tags"] == "tag1,tag2,tag3"

    entries = load_index(tmp_index_path)
    assert entries[0].description == tricky_description
    assert entries[0].tags == "tag1,tag2,tag3"


def test_register_from_genbank(sample_vector_record, tmp_index_path, tmp_path):
    gb_path = tmp_path / "vector.gb"
    sample_vector_record.to_genbank(gb_path)

    entry = register_from_genbank(
        tmp_index_path, gb_path, kind="plasmid", description="test vector registration"
    )

    assert entry.id == sample_vector_record.name
    assert entry.length == sample_vector_record.length
    assert entry.kind == "plasmid"

    entries = load_index(tmp_index_path)
    assert len(entries) == 1
    assert entries[0].path == str(gb_path)
    assert entries[0].description == "test vector registration"
