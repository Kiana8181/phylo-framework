import argparse
import sys
import time
import os
import pandas as pd
import numpy as np
import subprocess
from pathlib import Path
from Bio import SeqIO, AlignIO


def load_airr_data(filepath):
    """
    Reads AIRR formatted TSV, constructs whole/germline sequences,
    and filters invalid rows.
    """
    cols_to_use = [
        "sequence_id",
        "sequence",
        "v_identity",
        "d_identity",
        "j_identity",
        "cdr1",
        "cdr2",
        "cdr3",
        "fwr1",
        "fwr2",
        "fwr3",
        "fwr4",
        "v_germline_alignment",
        "d_germline_alignment",
        "j_germline_alignment",
        "np1",
        "np2",
        "v_sequence_start",
        "cdr1_start",
        "cdr1_end",
        "cdr2_start",
        "cdr2_end",
        "cdr3_start",
        "cdr3_end",
        "d_sequence_start",
        "d_sequence_end",
    ]

    try:
        df_header = pd.read_csv(filepath, sep="\t", nrows=0)
    except pd.errors.EmptyDataError:
        print(f"Error: The AIRR file '{filepath}' is empty.")
        sys.exit(1)

    valid_cols = list(set(cols_to_use).intersection(df_header.columns))

    # Load data
    df = pd.read_csv(filepath, sep="\t", usecols=valid_cols)

    # Force sequence_id to string and strip whitespace
    df["sequence_id"] = df["sequence_id"].astype(str).str.strip()

    # Fill only string columns with empty string
    str_cols = df.select_dtypes(include=["object"]).columns
    df[str_cols] = df[str_cols].fillna("")

    # Construct Sequences
    region_cols = ["fwr1", "cdr1", "fwr2", "cdr2", "fwr3", "cdr3", "fwr4"]
    for c in region_cols:
        if c not in df.columns:
            df[c] = ""
    df["whole_seq"] = df[region_cols].astype(str).agg("".join, axis=1)

    germ_cols = [
        "v_germline_alignment",
        "np1",
        "d_germline_alignment",
        "np2",
        "j_germline_alignment",
    ]
    for c in germ_cols:
        if c not in df.columns:
            df[c] = ""
    df["germline_seq"] = (
        df[germ_cols].astype(str).agg("".join, axis=1).str.replace(".", "", regex=False)
    )

    # Filter Invalid Rows
    df.replace("", np.nan, inplace=True)

    subset_check = [
        "cdr1_start",
        "cdr1_end",
        "cdr2_start",
        "cdr2_end",
        "cdr3_start",
        "cdr3_end",
        "v_sequence_start",
        "d_sequence_start",
        "d_sequence_end",
        "v_identity",
        "j_identity",
    ]
    subset_check = [c for c in subset_check if c in df.columns]

    initial_len = len(df)
    df.dropna(subset=subset_check, how="any", inplace=True)
    dropped = initial_len - len(df)
    if dropped > 0:
        print(
            f"Warning: {dropped} sequences dropped from AIRR file due to missing coordinates/identities."
        )

    return df


def load_seq_info(filepath):
    """
    Reads the custom seq_info file.
    Handles both headerless files and files with headers (Change-O format).
    """
    try:
        # Detect separator automatically
        df = pd.read_csv(filepath, sep=None, engine="python")
    except Exception as e:
        print(f"Error reading Seq Info file: {e}")
        sys.exit(1)

    df.columns = df.columns.str.strip()

    # Check for headers
    if "sequence_id" in df.columns:
        if "clone_clonotype_id" in df.columns:
            target_clone_col = "clone_clonotype_id"
        elif "clone_id" in df.columns:
            target_clone_col = "clone_id"
        else:
            target_clone_col = df.columns[0]

        df = df[[target_clone_col, "sequence_id"]].copy()
        df.rename(columns={target_clone_col: "clone_id"}, inplace=True)

    else:
        print(
            "Warning: 'sequence_id' header not found. Assuming column 0 is CloneID and column 1 is SeqID."
        )
        df = pd.read_csv(filepath, sep=r"\s+", header=None)
        if len(df.columns) < 2:
            print("Error: Seq Info file has fewer than 2 columns.")
            sys.exit(1)
        df = df.iloc[:, [0, 1]]
        df.columns = ["clone_id", "sequence_id"]

    # Normalize IDs
    df["sequence_id"] = df["sequence_id"].astype(str).str.strip()
    df["clone_id"] = df["clone_id"].astype(str).str.strip()

    return df


def write_input_alignment_outputs(airr_filepath, seq_info_filepath, rep_name, size):
    """Write tree-input FASTA files from an existing aligned AIRR column."""
    airr_df = pd.read_csv(airr_filepath, sep="\t", dtype=str).fillna("")
    seq_info_df = load_seq_info(seq_info_filepath)

    required = {"sequence_id", "sequence_alignment"}
    missing = required - set(airr_df.columns)
    if missing:
        raise ValueError(
            "Pre-aligned mode requires columns: " + ", ".join(sorted(missing))
        )

    germline_column = next(
        (
            column
            for column in ("germline_alignment_d_mask", "germline_alignment")
            if column in airr_df.columns
        ),
        None,
    )
    if germline_column is None:
        raise ValueError(
            "Pre-aligned mode requires germline_alignment_d_mask "
            "(or germline_alignment) for the germline root."
        )

    selected_clones = get_top_clonotypes(seq_info_df, size)
    selected_ids = set(
        seq_info_df.loc[
            seq_info_df["clone_id"].isin(selected_clones), "sequence_id"
        ].astype(str)
    )
    selected = airr_df[airr_df["sequence_id"].isin(selected_ids)].copy()
    selected = selected[selected["sequence_alignment"].astype(str).str.len() > 0]
    if selected.empty:
        raise ValueError("No selected sequences have a non-empty sequence_alignment.")

    germline_values = selected[germline_column].astype(str).str.strip()
    germline_values = germline_values[germline_values != ""]
    if germline_values.empty:
        raise ValueError(f"Selected sequences have no non-empty {germline_column}.")
    germline = germline_values.iloc[0]

    lengths = set(selected["sequence_alignment"].astype(str).str.len())
    lengths.add(len(germline))
    if len(lengths) != 1:
        raise ValueError(
            "Pre-aligned sequences and germline must all have the same length."
        )

    with open(f"{rep_name}_matching_sequences.txt", "w") as handle:
        for aligned_sequence, group in selected.groupby(
            "sequence_alignment", sort=False
        ):
            representative_id = str(group.iloc[0]["sequence_id"])
            for sequence_id in group["sequence_id"].astype(str):
                if sequence_id != representative_id:
                    handle.write(f"{sequence_id}\t{representative_id}\n")

    records = [("germline", germline)]
    for aligned_sequence, group in selected.groupby(
        "sequence_alignment", sort=False
    ):
        representative_id = str(group.iloc[0]["sequence_id"])
        records.append(
            (f"{representative_id}@{len(group)}", str(aligned_sequence))
        )

    selected_fasta = Path(f"{rep_name}_selected_seq.fasta")
    unique_alignment = Path(f"{rep_name}_uniq.aln.fa")
    all_alignment = Path(f"{rep_name}_all.aln.fa")

    def write_records(path, preserve_abundance):
        with path.open("w") as handle:
            for header, sequence in records:
                output_header = (
                    header if preserve_abundance else header.split("@", 1)[0]
                )
                handle.write(f">{output_header}\n{sequence}\n")

    write_records(selected_fasta, preserve_abundance=True)
    write_records(unique_alignment, preserve_abundance=True)
    write_records(all_alignment, preserve_abundance=False)


def get_top_clonotypes(seq_info_df, n_clonotypes):
    counts = seq_info_df["clone_id"].value_counts()
    if n_clonotypes == "all":
        selected_ids = counts.index.tolist()
    else:
        selected_ids = counts.head(int(n_clonotypes)).index.tolist()
    return selected_ids


def select_representatives(seq_info_df, airr_df, selected_clones):
    subset_info = seq_info_df[seq_info_df["clone_id"].isin(selected_clones)]

    if subset_info.empty:
        print(
            f"Error: No sequences found matching the top {len(selected_clones)} clonotypes."
        )
        sys.exit(1)

    merged = subset_info.merge(
        airr_df[["sequence_id", "whole_seq", "v_identity"]],
        on="sequence_id",
        how="inner",
    )

    if merged.empty:
        print(
            "\nCRITICAL ERROR: No matching sequences found after merging AIRR data and Sequence Info."
        )
        sys.exit(1)

    representatives = []
    sequence_mapping = {}
    abundance_map = {}

    grouped = merged.groupby("clone_id")

    for clone_id, group in grouped:
        seq_counts = group["whole_seq"].value_counts()
        top_seq_str = seq_counts.index[0]

        rep_row = group[group["whole_seq"] == top_seq_str].iloc[0]
        rep_id = rep_row["sequence_id"]
        v_id = rep_row["v_identity"]

        d_val = airr_df.loc[airr_df["sequence_id"] == rep_id, "d_identity"].values[0]
        j_val = airr_df.loc[airr_df["sequence_id"] == rep_id, "j_identity"].values[0]

        representatives.append(
            {
                "clone_id": clone_id,
                "sequence_id": rep_id,
                "v_identity": v_id,
                "d_identity": d_val,
                "j_identity": j_val,
                "whole_seq": top_seq_str,
            }
        )

        dupes = group[group["whole_seq"] == top_seq_str]["sequence_id"].tolist()
        abundance_map[rep_id] = dupes

        for d_id in dupes:
            if d_id != rep_id:
                sequence_mapping[d_id] = rep_id

    return pd.DataFrame(representatives), sequence_mapping, abundance_map


def find_global_germline(representatives_df, abundance_map):
    if representatives_df.empty:
        print("Error: No representatives found. Cannot select germline.")
        sys.exit(1)

    representatives_df["abundance"] = representatives_df["sequence_id"].apply(
        lambda x: len(abundance_map.get(x, []))
    )

    max_v = representatives_df["v_identity"].max()
    candidates = representatives_df[representatives_df["v_identity"] == max_v].copy()

    candidates.sort_values(
        by=["j_identity", "d_identity", "abundance"],
        ascending=[False, False, False],
        inplace=True,
    )

    best_germ_id = candidates.iloc[0]["sequence_id"]
    return best_germ_id


def run_muscle_alignment(input_fasta, output_aln):
    muscle_cmd = "muscle"

    if os.path.exists("./muscle"):
        muscle_cmd = "./muscle"
    elif os.path.exists("./muscle.exe"):
        muscle_cmd = "muscle.exe"

    # DETECT MUSCLE VERSION
    try:
        ver_proc = subprocess.run(
            [muscle_cmd, "-version"], capture_output=True, text=True
        )
        version_out = ver_proc.stdout + ver_proc.stderr
    except Exception:
        version_out = ""

    # Set flags based on version
    if "muscle 5" in version_out.lower():
        print(f"Detected MUSCLE v5. Using modern syntax.")
        cmd = [muscle_cmd, "-align", str(input_fasta), "-output", str(output_aln)]
    else:
        print(f"Detected MUSCLE v3 (or unknown). Using legacy syntax.")
        cmd = [muscle_cmd, "-in", str(input_fasta), "-out", str(output_aln)]

    try:
        subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error running MUSCLE command: {' '.join(cmd)}")
        print(e.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: '{muscle_cmd}' executable not found.")
        sys.exit(1)


def map_gap_coordinates(aligned_seq, regions_dict):
    ungapped_to_gapped = []

    curr_gapped_idx = 0
    for char in aligned_seq:
        if char != "-":
            ungapped_to_gapped.append(curr_gapped_idx)
        curr_gapped_idx += 1

    ungapped_to_gapped.append(curr_gapped_idx)

    def get_gapped(idx):
        if idx < len(ungapped_to_gapped):
            return ungapped_to_gapped[idx]
        return len(aligned_seq)

    mapped_indices = []
    targets = [
        regions_dict["cdr1_start"],
        regions_dict["cdr1_end"],
        regions_dict["cdr2_start"],
        regions_dict["cdr2_end"],
        regions_dict["cdr3_start"],
        regions_dict["d_start"],
        regions_dict["d_end"],
        regions_dict["cdr3_end"],
    ]

    for t in targets:
        mapped_indices.append(get_gapped(int(t)))

    return mapped_indices


def get_regions_from_df(row):
    v_start = float(row["v_sequence_start"])

    def rel(val, offset=0):
        return int(float(val)) - int(v_start) + offset

    return {
        "cdr1_start": rel(row["cdr1_start"]),
        "cdr1_end": rel(row["cdr1_end"], 1),
        "cdr2_start": rel(row["cdr2_start"]),
        "cdr2_end": rel(row["cdr2_end"], 1),
        "cdr3_start": rel(row["cdr3_start"]),
        "cdr3_end": rel(row["cdr3_end"], 1),
        "d_start": rel(row["d_sequence_start"]),
        "d_end": rel(row["d_sequence_end"], 1),
    }


def compare_seq_to_germline(seq_str, germ_str):
    res = []
    for s, g in zip(seq_str, germ_str):
        if s == g and s != "-":
            res.append(".")
        else:
            res.append(s)
    return "".join(res)


def write_outputs(
    repertoire_name,
    aligned_records,
    best_germ_id,
    airr_df,
    abundance_map,
    total_clonotypes,
):

    germline_aligned = ""
    for rec in aligned_records:
        if rec.id == "germline":
            germline_aligned = str(rec.seq)
            break

    out_txt = f"{repertoire_name}_aligned_regions.txt"
    processed_data = {}

    germ_row = airr_df[airr_df["sequence_id"] == best_germ_id].iloc[0]
    germ_regions = get_regions_from_df(germ_row)
    germ_splits = map_gap_coordinates(germline_aligned, germ_regions)

    processed_data["germline"] = {
        "seq": germline_aligned,
        "splits": germ_splits,
        "id": "germline",
        "count": "_",
        "v_ident": "_",
    }

    for rec in aligned_records:
        if rec.id == "germline":
            continue

        original_id = rec.id.split("@")[0]

        row = airr_df[airr_df["sequence_id"] == original_id]
        if row.empty:
            continue
        row = row.iloc[0]

        regions = get_regions_from_df(row)
        splits = map_gap_coordinates(str(rec.seq), regions)

        count = len(abundance_map.get(original_id, [original_id]))
        perc = count / total_clonotypes
        count_str = f"{count}({perc:.5f})"

        comp_seq = compare_seq_to_germline(str(rec.seq), germline_aligned)

        processed_data[original_id] = {
            "seq": comp_seq,
            "splits": splits,
            "id": original_id,
            "count": count_str,
            "v_ident": row["v_identity"],
        }

    with open(out_txt, "w") as f:

        def write_line(data_dict):
            s = data_dict["seq"]
            sp = data_dict["splits"]

            parts = [
                s[0 : sp[0]],
                s[sp[0] : sp[1]],
                s[sp[1] : sp[2]],
                s[sp[2] : sp[3]],
                s[sp[3] : sp[4]],
                s[sp[4] : sp[5]],
                s[sp[5] : sp[6]],
                s[sp[6] : sp[7]],
                s[sp[7] :],
            ]

            line_items = [
                data_dict["id"],
                data_dict["count"],
                str(data_dict["v_ident"]),
            ] + parts
            f.write("\t".join(line_items) + "\n")

        write_line(processed_data["germline"])
        for pid, pdata in processed_data.items():
            if pid != "germline":
                write_line(pdata)


def main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Intraclonal Alignment Tool")
    parser.add_argument("-a", "--airr", required=True, help="AIRR formatted TSV file")
    parser.add_argument(
        "-f", "--seq_info", required=True, help="Sequence Info / Clonotype map file"
    )
    parser.add_argument(
        "-n", "--name", required=True, help="Repertoire Name (Output Prefix)"
    )
    parser.add_argument(
        "-s",
        "--size",
        required=True,
        help="Number of clonotypes to analyze (int or 'all')",
    )
    parser.add_argument(
        "--use-input-alignment",
        action="store_true",
        help="Use sequence_alignment directly instead of running MUSCLE.",
    )

    args = parser.parse_args()

    rep_name = f"{args.name}_{args.size}"

    if args.use_input_alignment:
        write_input_alignment_outputs(
            args.airr,
            args.seq_info,
            rep_name,
            args.size,
        )
        print("Using existing sequence_alignment; skipped MUSCLE.")
        return

    print(f"Loading data for {rep_name}...")
    airr_df = load_airr_data(args.airr)
    seq_info_df = load_seq_info(args.seq_info)

    selected_clones = get_top_clonotypes(seq_info_df, args.size)
    print(f"Selected {len(selected_clones)} clonotypes.")

    reps_df, seq_mapping, abundance_map = select_representatives(
        seq_info_df, airr_df, selected_clones
    )

    best_germ_id = find_global_germline(reps_df, abundance_map)
    germline_seq_str = airr_df[airr_df["sequence_id"] == best_germ_id][
        "germline_seq"
    ].values[0]
    print(f"Selected Global Germline Reference: {best_germ_id}")

    with open(f"{rep_name}_matching_sequences.txt", "w") as f:
        for orig, rep in seq_mapping.items():
            f.write(f"{orig}\t{rep}\n")

    fasta_path = Path(f"{rep_name}_selected_seq.fasta")
    with open(fasta_path, "w") as f:
        f.write(f">germline\n{germline_seq_str}\n")
        for _, row in reps_df.iterrows():
            seq_id = row["sequence_id"]
            count = len(abundance_map.get(seq_id, []))
            f.write(f">{seq_id}@{count}\n{row['whole_seq']}\n")

    print("Running MUSCLE alignment...")
    aln_path = Path(f"{rep_name}.aln")
    run_muscle_alignment(fasta_path, aln_path)

    uniq_aln_path = Path(f"{rep_name}_uniq.aln.fa")
    try:
        alignments = AlignIO.read(aln_path, "fasta")
        SeqIO.write(alignments, uniq_aln_path, "fasta")
    except ValueError:
        print(
            "Error reading alignment file. MUSCLE might have failed to produce output."
        )
        sys.exit(1)

    aligned_seq_dict = {rec.id.split("@")[0]: str(rec.seq) for rec in alignments}

    with open(f"{rep_name}_all.aln.fa", "w") as f:
        for seq_id, aln_seq in aligned_seq_dict.items():
            if seq_id == "germline":
                f.write(f">germline\n{aln_seq}\n")
                continue

            f.write(f">{seq_id}\n{aln_seq}\n")
            if seq_id in abundance_map:
                for dup_id in abundance_map[seq_id]:
                    if dup_id != seq_id:
                        f.write(f">{dup_id}\n{aln_seq}\n")

    print("Generating aligned regions report...")
    total_seqs_analyzed = len(seq_info_df)
    write_outputs(
        rep_name,
        list(alignments),
        best_germ_id,
        airr_df,
        abundance_map,
        total_seqs_analyzed,
    )

    print(f"Execution time: {time.time() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
