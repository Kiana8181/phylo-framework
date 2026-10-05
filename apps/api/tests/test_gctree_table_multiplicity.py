from apps.api.preprocess.converters import ConversionError, convert_table_to_aligned_fasta


def test_duplicate_count_is_ignored_with_structured_warning(tmp_path):
    source = tmp_path / "input.tsv"
    output = tmp_path / "input.fasta"
    source.write_text(
        "sequence_id\tsequence_alignment\tduplicate_count\ncellA\tACGT\t3\n",
        encoding="utf-8",
    )

    result = convert_table_to_aligned_fasta(
        source,
        output,
        id_column="sequence_id",
        aligned_seq_column="sequence_alignment",
        delimiter="tsv",
    )

    assert result["n_records"] == 1
    assert output.read_text(encoding="utf-8") == ">cellA\nACGT\n"
    assert result["warnings"][0]["code"] == "IGNORED_DUPLICATE_COUNT"


def test_three_distinct_ids_produce_three_records(tmp_path):
    source = tmp_path / "input.csv"
    output = tmp_path / "input.fasta"
    source.write_text(
        "sequence_id,sequence_alignment\n"
        "cellA_copy1,ACGT\ncellA_copy2,ACGT\ncellA_copy3,ACGT\n",
        encoding="utf-8",
    )
    result = convert_table_to_aligned_fasta(
        source,
        output,
        id_column="sequence_id",
        aligned_seq_column="sequence_alignment",
        delimiter="csv",
    )
    assert result["n_records"] == 3
    assert output.read_text(encoding="utf-8").count(">cellA_copy") == 3


def test_repeated_identifier_remains_invalid(tmp_path):
    source = tmp_path / "input.tsv"
    source.write_text(
        "sequence_id\tsequence_alignment\ncellA\tACGT\ncellA\tACGT\n",
        encoding="utf-8",
    )
    try:
        convert_table_to_aligned_fasta(
            source,
            tmp_path / "output.fasta",
            id_column="sequence_id",
            aligned_seq_column="sequence_alignment",
            delimiter="tsv",
        )
    except ConversionError as exc:
        assert exc.code == "DUPLICATE_IDS"
    else:
        raise AssertionError("duplicate identifier was accepted")
