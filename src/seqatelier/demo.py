"""Deterministic synthetic records for installation and MCP checks."""

import random

from Bio.SeqFeature import SeqFeature, SimpleLocation

from seqatelier.core.sequence import LabRecord
from seqatelier.workspace import Workspace, genbank_text


def initialize_demo(workspace: Workspace) -> None:
    workspace.initialize()
    existing = {r["id"] for r in workspace.list_records(limit=1000)}
    rng = random.Random(20261004)
    dna = "".join(rng.choice("ACGT") for _ in range(1200))
    cds = "ATG" + "GCTGGTGAACTG" * 20 + "TAA"
    dna = dna[:300] + cds + dna[300 + len(cds) :]
    vector = LabRecord.from_sequence(dna, "demo_vector", "Synthetic demonstration vector", circular=True)
    vector.record.features.append(
        SeqFeature(
            SimpleLocation(300, 300 + len(cds), strand=1), type="CDS", qualifiers={"label": ["demo_CDS"]}
        )
    )
    insert = LabRecord.from_sequence(
        "ATG" + "GCTGAAGGTACT" * 15 + "TAA", "demo_insert", "Synthetic demonstration fragment"
    )
    insert.record.features.append(
        SeqFeature(
            SimpleLocation(0, insert.length, strand=1), type="CDS", qualifiers={"label": ["insert_CDS"]}
        )
    )
    for identifier, record, kind in [("demo-vector", vector, "plasmid"), ("demo-insert", insert, "fragment")]:
        if identifier not in existing:
            workspace.import_record(genbank_text(record), record_id=identifier, kind=kind)
