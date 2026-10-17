import sys
from optparse import OptionParser
import os
from pathlib import Path
import Levenshtein
from ClusterCDR3Only import FaIR_CDR3Only
import time
import pandas as pd

# Add project's root to $PATH (os path)
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

# These must be done after $PATH modification.
from config.path import ROOT_DIR
from src.util import read_tsv, write_tsv


def same_vj_gene_map(df: pd.DataFrame):
    """
    Find rows with same V and J gene.
    returns a mapping from concat gene to sequence_id.
    """

    # Delete allels
    v_gene_only = df["v_call"].astype(str).str.split("*").str[0]
    j_gene_only = df["j_call"].astype(str).str.split("*").str[0]

    # Temporary column with (V_gene + "_" + J_gene)
    df["temp_VJ"] = v_gene_only + "_" + j_gene_only

    # e.g. {'IGHV4-38-2_IGHJ5': ['S1', 'S4', 'S6', 'S9', 'S10']}
    same_vj_to_seq_id_map = df.groupby("temp_VJ")["sequence_id"].apply(list).to_dict()

    df.drop(columns=["temp_VJ"], inplace=True)

    return same_vj_to_seq_id_map


def group_clone_VJ_cdr3(same_vj_to_seq_id_map, df, threshold, output_dir):
    """
    Calculate clones based on VJ and CDR3 identity.
    """

    # Mapping: sequence_id -> cdr3_aa
    cdr3_lookup = dict(zip(df["sequence_id"], df["cdr3_aa"]))

    VJ_ID_diff_CDR3 = {}

    for VJ_id, seq_ids in same_vj_to_seq_id_map.items():
        if not seq_ids:
            continue

        if VJ_id.split("_")[1] == "IGHJ6":
            tolerance_val = 1
        else:
            tolerance_val = 0

        # Construct loclist for FaIR_CDR3Only
        try:
            first_seq_id = seq_ids[0]
            ref_length = len(cdr3_lookup[first_seq_id])
        except KeyError:
            continue

        loclist = []
        for seq_id in seq_ids:
            if seq_id in cdr3_lookup:
                loclist.append(
                    {"Id": seq_id, "CDR3": cdr3_lookup[seq_id], "Length": ref_length}
                )

        clusters = FaIR_CDR3Only(
            loclist,
            output_dir,
            th=threshold * 100,
            tolerance=tolerance_val,
            mth=threshold * 100,
            split_size=250,
        )

        # Initialize the nested dictionary for this VJ_id
        VJ_ID_diff_CDR3[VJ_id] = {}

        for c in clusters:
            CDR3_seq = c[0]["CDR3"]
            VJ_ID_diff_CDR3[VJ_id][CDR3_seq] = [seq["Id"] for seq in c]

    return VJ_ID_diff_CDR3


import pandas as pd


def add_clone_id(same_vj_diff_cdr3_seq_id_map, df):
    """
    Assigns clone IDs to a dataframe based on same_vj_diff_cdr3_seq_id_map.
    """

    # Create a flat mapping dictionary: sequence_id -> clone_id
    # This allows for O(1) lookup speed.
    id_to_clone_map = {}
    current_clone_id = 0

    for cdr3_seq_id_map in same_vj_diff_cdr3_seq_id_map.values():
        for seq_id_list in cdr3_seq_id_map.values():
            for seq_id in seq_id_list:
                id_to_clone_map[seq_id] = current_clone_id

            current_clone_id += 1

    clone_id_column = df["sequence_id"].map(id_to_clone_map)

    if "clone_id" in df.columns:
        df.drop(columns=["clone_id"], inplace=True)
    df.insert(0, "clone_id", clone_id_column)

    # Change clone_id type to int
    df["clone_id"] = df["clone_id"].astype("Int64")

    # Extract number in sequnce_id and sort.
    # The number is only a sort key, so ids that carry no digits (for example a
    # germline row named 'naive') must not abort the run. They sort first.
    df["sequence_id_num"] = (
        pd.to_numeric(
            df["sequence_id"].astype(str).str.extract(r"(\d+)", expand=False),
            errors="coerce",
        )
        .fillna(-1)
        .astype("int64")
    )
    df.sort_values(by=["clone_id", "sequence_id_num"], inplace=True)
    df.drop(columns=["sequence_id_num"], inplace=True)

    df.reset_index(drop=True, inplace=True)


def main():
    start_time = time.time()
    usage = "python initial_clustering.py -i <format_labeling_imgt_airr.py output> -o <output path> -s <CDR3 threshold>"
    parser = OptionParser(usage)
    parser.add_option(
        "-i",
        "--input",
        dest="input",
        help="input file path, output of format_labeling_imgt_airr.py",
        type="string",
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
        "--threshold",
        dest="threshold",
        help="Clone identity percentage between 0 and 1",
        type="float",
    )

    options, _ = parser.parse_args()
    if not options.input or not options.output_dir or not options.threshold:
        parser.error("Bad inputs")

    data_df = read_tsv(options.input)
    print(f"Info - initial_clustering.py - input df shape: {data_df.shape}")

    # drop rows without value in their cdr3_aa, v_call or j_call
    data_df.dropna(subset=["cdr3_aa", "v_call", "j_call"], inplace=True)

    # Filter rows with only "_" in them
    data_df = data_df[~(data_df == "_").any(axis=1)]

    same_vj_to_seq_id_map = same_vj_gene_map(data_df)

    # e.g. {'IGHV1-2_IGHJ5': {'ARGSADRNNWFDS': ['S10614', 'S102539'], 'AREYSSSSNYYGMDV': ['S16047', 'S20979']}}
    same_vj_diff_cdr3_seq_id_map = group_clone_VJ_cdr3(
        same_vj_to_seq_id_map, data_df, float(options.threshold), options.output_dir
    )

    add_clone_id(same_vj_diff_cdr3_seq_id_map, data_df)

    os.makedirs(options.output_dir, exist_ok=True)
    file_name = f"sameVJ_noallele_CDR3_{options.threshold}.tsv"
    output_file_path = os.path.join(options.output_dir, file_name)
    write_tsv(data_df, output_file_path)

    end_time = time.time()
    print(f"initial_clustering.py finished. Execution Time: {end_time-start_time}")

    clone_id_seq_ids_map_df = (
        data_df.groupby("clone_id")["sequence_id"]
        .apply(lambda x: " ".join(x))
        .reset_index()
    )
    clone_id_seq_ids_map_df.columns = ["clone_id", "sequence_ids"]
    write_tsv(
        clone_id_seq_ids_map_df,
        os.path.join(options.output_dir, "initial_clusters_Fo.tsv"),
    )


if __name__ == "__main__":
    main()
