from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from apps.api.preprocess.column_requirements import (
    CLONALTREE_REQUIRED_KEYS,
    DOWSER_REQUIRED_KEYS,
    GCTREE_TABULAR_REQUIRED_KEYS,
)
from apps.api.preprocess.converters import ConversionError, rename_table_columns
from apps.api.preprocess.prepare_input import (
    PreprocessError,
    prepare_input_for_method,
    should_apply_column_mapping,
)


def _write_table(path: Path, header: list[str], rows: list[list[str]], delimiter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _read_header(path: Path, delimiter: str) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = list(reader)
    return rows[0] if rows else []


class RenameTableColumnsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="phylo_preprocess_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_rename_table_columns_happy_path_with_normalized_match(self) -> None:
        input_path = self._tmpdir / "input.csv"
        output_path = self._tmpdir / "output.csv"

        header = [
            "Seq ID",
            "Clone-ID",
            "Aligned Sequence",
            "GL Mask",
            "V Call",
            "J Call",
            "Junction",
            "extra",
        ]
        rows = [["s1", "c1", "AAAA", "----", "IGHV1", "IGHJ4", "CARDR", "x"]]
        _write_table(input_path, header, rows, ",")

        stats = rename_table_columns(
            input_path,
            output_path,
            delimiter="csv",
            column_map={
                "sequence_id": "seq id",
                "clone_id": "clone-id",
                "sequence_alignment": "aligned sequence",
                "germline_alignment_d_mask": "gl mask",
                "v_call": "v call",
                "j_call": "j call",
                "junction": "junction",
            },
            required_keys=DOWSER_REQUIRED_KEYS,
        )

        renamed_header = _read_header(output_path, ",")
        self.assertEqual(
            renamed_header,
            [
                "sequence_id",
                "clone_id",
                "sequence_alignment",
                "germline_alignment_d_mask",
                "v_call",
                "j_call",
                "junction",
                "extra",
            ],
        )
        self.assertEqual(stats["rows"], 1)
        self.assertEqual(stats["cols"], 8)
        self.assertEqual(stats["resolved_map"]["sequence_id"], "Seq ID")

    def test_rename_table_columns_missing_mapped_source_column(self) -> None:
        input_path = self._tmpdir / "input.csv"
        output_path = self._tmpdir / "output.csv"
        _write_table(input_path, ["id", "value"], [["a", "1"]], ",")

        with self.assertRaises(ConversionError) as ctx:
            rename_table_columns(
                input_path,
                output_path,
                delimiter="csv",
                column_map={"sequence_id": "missing_col"},
                required_keys=["sequence_id"],
            )

        self.assertEqual(ctx.exception.code, "COLUMN_NOT_FOUND")

    def test_rename_table_columns_ambiguous_column_match(self) -> None:
        input_path = self._tmpdir / "input.csv"
        output_path = self._tmpdir / "output.csv"
        _write_table(input_path, ["Seq-ID", "Seq ID"], [["a", "b"]], ",")

        with self.assertRaises(ConversionError) as ctx:
            rename_table_columns(
                input_path,
                output_path,
                delimiter="csv",
                column_map={"sequence_id": "seq id"},
                required_keys=["sequence_id"],
            )

        self.assertEqual(ctx.exception.code, "AMBIGUOUS_COLUMN")

    def test_rename_table_columns_missing_required_mapping(self) -> None:
        input_path = self._tmpdir / "input.csv"
        output_path = self._tmpdir / "output.csv"
        _write_table(input_path, ["foo", "bar"], [["1", "2"]], ",")

        with self.assertRaises(ConversionError) as ctx:
            rename_table_columns(
                input_path,
                output_path,
                delimiter="csv",
                column_map={},
                required_keys=["sequence_id"],
            )

        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_MAPPING")
        self.assertEqual(ctx.exception.details.get("missing_required_keys"), ["sequence_id"])

    def test_rename_table_columns_duplicate_target_header_collision(self) -> None:
        input_path = self._tmpdir / "input.csv"
        output_path = self._tmpdir / "output.csv"
        _write_table(input_path, ["sequence_id", "Seq ID"], [["s1", "s2"]], ",")

        with self.assertRaises(ConversionError) as ctx:
            rename_table_columns(
                input_path,
                output_path,
                delimiter="csv",
                column_map={"sequence_id": "Seq ID"},
                required_keys=["sequence_id"],
            )

        self.assertEqual(ctx.exception.code, "AMBIGUOUS_COLUMN")


class PrepareInputMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="phylo_prepare_input_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_prepare_input_clonaltree_csv_mapping_chain(self) -> None:
        input_path = self._tmpdir / "input.csv"
        work_dir = self._tmpdir / "work_csv"
        header = [
            "Seq ID",
            "Productive Flag",
            "V Gene",
            "D Gene",
            "J Gene",
            "Seq Align",
            "J Align",
            "V Align",
            "J Align AA",
            "V Align AA",
            "Junction AA",
            "CDR3 AA",
        ]
        rows = [["s1", "T", "IGHV1", "IGHD1", "IGHJ4", "AAAA", "AA", "AA", "KK", "KK", "CAR", "CAR"]]
        _write_table(input_path, header, rows, ",")

        params = {
            "doMapping": True,
            "column_map": {
                "sequence_id": "Seq ID",
                "productive": "Productive Flag",
                "v_call": "V Gene",
                "d_call": "D Gene",
                "j_call": "J Gene",
                "sequence_alignment": "Seq Align",
                "j_sequence_alignment": "J Align",
                "v_sequence_alignment": "V Align",
                "j_sequence_alignment_aa": "J Align AA",
                "v_sequence_alignment_aa": "V Align AA",
                "junction_aa": "Junction AA",
                "cdr3_aa": "CDR3 AA",
            },
        }

        prepared = prepare_input_for_method(
            "clonaltree",
            input_path,
            params=params,
            work_dir=work_dir,
        )

        self.assertEqual(prepared.final_ext, "tsv")
        self.assertEqual(
            [step["step"] for step in prepared.applied_steps],
            ["rename_table_columns", "convert_csv_to_tsv"],
        )
        renamed_header = _read_header(prepared.final_path, "\t")
        self.assertEqual(renamed_header[: len(CLONALTREE_REQUIRED_KEYS)], CLONALTREE_REQUIRED_KEYS)

    def test_prepare_input_clonaltree_tsv_mapping_rename_only(self) -> None:
        input_path = self._tmpdir / "input.tsv"
        work_dir = self._tmpdir / "work_tsv"
        header = CLONALTREE_REQUIRED_KEYS.copy()
        rows = [["s1", "T", "IGHV1", "IGHD1", "IGHJ4", "AAAA", "AA", "AA", "KK", "KK", "CAR", "CAR"]]
        _write_table(input_path, header, rows, "\t")

        prepared = prepare_input_for_method(
            "clonaltree",
            input_path,
            params={"doMapping": True, "column_map": {}},
            work_dir=work_dir,
        )

        self.assertEqual(prepared.final_ext, "tsv")
        self.assertEqual([step["step"] for step in prepared.applied_steps], ["rename_table_columns"])

    def test_prepare_input_dowser_tsv_mapping_rename_only(self) -> None:
        input_path = self._tmpdir / "dowser.tsv"
        work_dir = self._tmpdir / "work_dowser"
        header = ["SeqID", "Clone", "Aligned", "Germline", "V", "J", "Junction"]
        rows = [["s1", "c1", "AAAA", "----", "IGHV1", "IGHJ4", "CAR"]]
        _write_table(input_path, header, rows, "\t")

        prepared = prepare_input_for_method(
            "dowser",
            input_path,
            params={
                "doMapping": True,
                "column_map": {
                    "sequence_id": "SeqID",
                    "clone_id": "Clone",
                    "sequence_alignment": "Aligned",
                    "germline_alignment_d_mask": "Germline",
                    "v_call": "V",
                    "j_call": "J",
                    "junction": "Junction",
                },
            },
            work_dir=work_dir,
        )

        self.assertEqual(prepared.final_ext, "tsv")
        self.assertEqual([step["step"] for step in prepared.applied_steps], ["rename_table_columns"])
        renamed_header = _read_header(prepared.final_path, "\t")
        self.assertEqual(renamed_header[: len(DOWSER_REQUIRED_KEYS)], DOWSER_REQUIRED_KEYS)

    def test_prepare_input_gctree_csv_mapping_then_fasta(self) -> None:
        input_path = self._tmpdir / "gctree.csv"
        work_dir = self._tmpdir / "work_gctree"
        _write_table(
            input_path,
            ["Sample ID", "Aligned Seq"],
            [["s1", "ACGT"], ["s2", "A-GT"]],
            ",",
        )

        prepared = prepare_input_for_method(
            "gctree",
            input_path,
            params={
                "doMapping": True,
                "column_map": {
                    "sequence_id": "Sample ID",
                    "sequence_alignment": "Aligned Seq",
                },
            },
            work_dir=work_dir,
        )

        self.assertEqual(prepared.final_ext, "fasta")
        self.assertEqual(
            [step["step"] for step in prepared.applied_steps],
            ["rename_table_columns", "convert_table_to_aligned_fasta"],
        )
        fasta_text = prepared.final_path.read_text(encoding="utf-8")
        self.assertIn(">s1\nACGT\n", fasta_text)
        self.assertIn(">s2\nA-GT\n", fasta_text)

    def test_prepare_input_missing_column_mapping_error_shape(self) -> None:
        input_path = self._tmpdir / "dowser_missing.tsv"
        work_dir = self._tmpdir / "work_missing"
        _write_table(input_path, ["foo", "bar"], [["a", "b"]], "\t")

        with self.assertRaises(PreprocessError) as ctx:
            prepare_input_for_method(
                "dowser",
                input_path,
                params={"doMapping": True},
                work_dir=work_dir,
            )

        self.assertEqual(ctx.exception.code, "MISSING_COLUMN_MAPPING")
        details = ctx.exception.details
        self.assertEqual(details.get("required_keys"), DOWSER_REQUIRED_KEYS)
        self.assertEqual(details.get("missing_keys"), DOWSER_REQUIRED_KEYS)
        self.assertIn("example_column_map", details)

    def test_should_apply_column_mapping_matrix(self) -> None:
        self.assertTrue(should_apply_column_mapping("dowser", "csv", {"doMapping": True}))
        self.assertTrue(should_apply_column_mapping("clonaltree", "tsv", {"doMapping": "true"}))
        self.assertTrue(should_apply_column_mapping("gctree", "csv", {"doMapping": 1}))

        self.assertFalse(should_apply_column_mapping("gctree", "fasta", {"doMapping": True}))
        self.assertFalse(should_apply_column_mapping("brepphylo", "csv", {"doMapping": True}))
        self.assertFalse(should_apply_column_mapping("dowser", "csv", {"doMapping": False}))
        self.assertFalse(should_apply_column_mapping("dowser", "csv", {}))

        # Tabular requirement for the gctree tabular adapter keys.
        self.assertEqual(GCTREE_TABULAR_REQUIRED_KEYS, ["sequence_id", "sequence_alignment"])


if __name__ == "__main__":
    unittest.main()
