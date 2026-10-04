import pytest
from Bio.Seq import Seq
from Bio.SeqFeature import CompoundLocation, SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord

from seqatelier.codon.optimize import best_codon
from seqatelier.core.orders import OrderPrimer
from seqatelier.core.sequence import LabRecord
from seqatelier.core.types import Primer, PrimerDesignError, PurificationGrade
from seqatelier.primer.quikchange import design_point_mutation_by_codon


def template(strand=1, offset=0):
    coding = "A" * offset + "ATGGCTGGTTAA"
    sequence = "GCGT" * 15 + (coding if strand == 1 else str(Seq(coding).reverse_complement())) + "GCGT" * 15
    feature = SeqFeature(
        SimpleLocation(60, 60 + len(coding), strand=strand),
        type="CDS",
        qualifiers={"label": ["synthetic"], "codon_start": [str(offset + 1)]},
    )
    return LabRecord(
        SeqRecord(
            Seq(sequence),
            id="test",
            name="test",
            features=[feature],
            annotations={"molecule_type": "DNA", "topology": "circular"},
        )
    )


@pytest.mark.parametrize("strand", [1, -1])
@pytest.mark.parametrize("offset", [0, 1, 2])
def test_cds_frame_and_reverse_strand(strand, offset):
    record = template(strand, offset)
    result = design_point_mutation_by_codon(
        record,
        2,
        "R",
        cds_feature_label="synthetic",
        host="human",
        flank_min_bp=12,
        flank_max_bp=12,
        annotate=False,
    )
    coding = best_codon("R", "human")
    genomic = coding if strand == 1 else str(Seq(coding).reverse_complement())
    assert result.primer_pair.forward.sequence[12:15] == genomic
    assert "A→R" in result.mutation_description
    assert len(record.record.features) == 1


def test_residue_outside_cds_rejected_even_inside_plasmid():
    with pytest.raises(PrimerDesignError, match="outside the CDS"):
        design_point_mutation_by_codon(template(), 5, "R", cds_feature_label="synthetic")


def test_join_boundary_and_nonstandard_translation_rejected():
    record = template()
    record.record.features[0].location = CompoundLocation(
        [SimpleLocation(60, 64, strand=1), SimpleLocation(80, 88, strand=1)]
    )
    with pytest.raises(PrimerDesignError, match="joined CDS"):
        design_point_mutation_by_codon(record, 2, "R", cds_feature_label="synthetic")
    record = template()
    record.record.features[0].qualifiers["transl_table"] = ["2"]
    with pytest.raises(PrimerDesignError, match="tables 1 and 11"):
        design_point_mutation_by_codon(record, 2, "R", cds_feature_label="synthetic")


@pytest.mark.parametrize(
    ("grade", "expected"),
    [
        (PurificationGrade.HPLC, "HPLC"),
        (PurificationGrade.PAGE, "HPLC"),
        (PurificationGrade.DESALT, "salt-free"),
    ],
)
def test_order_preserves_grade_and_text_notes(grade, expected):
    primer = Primer(
        name="synthetic",
        sequence="ATGCGCGCATGC",
        tm_celsius=50,
        gc_percent=60,
        purification=grade,
        notes=["first", "second"],
    )
    order = OrderPrimer.from_seqatelier_primer(primer)
    assert order.purification == expected
    assert order.design_notes == "first\nsecond"
