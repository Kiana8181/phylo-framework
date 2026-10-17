from optparse import OptionParser
from pathlib import Path
import re
import time
import sys
import os

# add project's root to os path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.util import read_tsv, write_tsv


# First IG gene token in a call string, with or without an allele suffix.
_GENE_CALL_RE = r"(IG[HKL][VDJ][A-Za-z0-9\-\./]*(?:\*\d+)?)"


def _gene_call_from_imgt_or_airr(series):
    """Extract one gene call from either IMGT HighV-QUEST or AIRR/IgBLAST input.

    IMGT HighV-QUEST writes 'Homsap IGHV1-69*01 F', and its D calls have
    historically arrived underscore-separated ('d_IGHD2-2*01_F'). AIRR/IgBLAST
    writes a bare call which may list several ambiguous alleles
    ('IGHD2-2*01,IGHD2-2*02,IGHD2-2*03').

    Taking the first IG token accepts every one of those forms and yields the
    first allele for ambiguous AIRR calls. Positional splitting is kept as a
    fallback so any non-IG dialect behaves as it did before.
    """
    text = series.astype(str)
    extracted = text.str.extract(_GENE_CALL_RE, expand=False)
    parts = text.str.split()
    fallback = parts.str[1].fillna(parts.str[0])
    return extracted.fillna(fallback)


def extract_required_data_from_airr(airr_file_path, abundance_threshold):
    df = read_tsv(airr_file_path)

    mask = df["sequence_alignment"].str.contains("N", case=False, na=False)
    df = df[~mask]

    counts = df.groupby("sequence_alignment")["sequence_alignment"].transform("size")
    df = df[counts > abundance_threshold]

    required_columns = {
        "sequence_id",
        "productive",
        "v_call",
        "d_call",
        "j_call",
        "sequence_alignment",
        "j_sequence_alignment",
        "v_sequence_alignment",
        "j_sequence_alignment_aa",
        "v_sequence_alignment_aa",
        "junction_aa",
        "cdr3_aa",
    }

    valid_cols = df.columns.intersection(required_columns)
    df = df[valid_cols].copy()

    df["cdr3_aa"] = df["cdr3_aa"].str.replace("#", ".", regex=False)
    df["v_call"] = _gene_call_from_imgt_or_airr(df["v_call"])
    df["j_call"] = _gene_call_from_imgt_or_airr(df["j_call"])
    df["d_call"] = _gene_call_from_imgt_or_airr(df["d_call"])

    return df


def main():
    start_time = time.time()
    usage = "Usage: format_labeling_imgt_airr.py -a airr_file_path -o output_file_name -t abundance_threshold"

    parser = OptionParser(usage=usage)
    parser.add_option(
        "-a", "--airr", dest="airr_file_path", help="airr tsv file path", type="string"
    )
    parser.add_option(
        "-o",
        "--output",
        dest="output_dir",
        help="output directory",
        type="string",
    )
    parser.add_option(
        "-t",
        "--abundance_threshold",
        dest="abundance_threshold",
        help="abundance threshold of unique sequences to be analyzed.",
        type="int",
    )

    options, _ = parser.parse_args()
    if not options.airr_file_path or not options.output_dir:
        parser.error("Bad inputs")

    data_df = extract_required_data_from_airr(
        options.airr_file_path, int(options.abundance_threshold)
    )

    os.makedirs(options.output_dir, exist_ok=True)
    file_name = "format_labeling_imgt_airr.tsv"
    output_file_path = os.path.join(options.output_dir, file_name)
    write_tsv(data_df, output_file_path)

    end_time = time.time()
    print(
        f"format_labeling_imgt_airr.py Reading AIRR finished. Execution Time: {end_time-start_time}"
    )


if __name__ == "__main__":
    main()
