import sys
import os
import time
import argparse
import pandas as pd
from pathlib import Path

# add project's root to os path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.util import read_tsv


def get_target_cluster_ids(repertoire_two_levels_info, nb_clone):
    """
    Reads the ranking file (File A, headerless) and extracts the top N cluster IDs.

    Logic:
    1. Read top N rows.
    2. Column 0 format is "Clone number <CLONE_NUMBER>".
    3. Split by space and take the 3rd element (index 2), e.g 64.
    """
    try:
        df_rank = read_tsv(repertoire_two_levels_info, header=None, nrows=int(nb_clone))

        if df_rank.empty:
            print("Warning: Ranking file is empty.")
            return []

        target_ids = df_rank[0].astype(str).apply(lambda x: x.split(" ")[2])
        return target_ids.tolist()

    except Exception as e:
        print(f"Error reading ranking file: {e}")
        sys.exit(1)


def process_sequences(final_clusters_seq_info, target_ids, output_dir):
    """
    Reads the sequence file (File B, with header), filters for target IDs,
    and writes separate output files.

    Logic:
    1. Read TSV with header.
    2. Create a temporary matching column by splitting 'clone_clonotype_id' (e.g. '0_0' -> '0').
    3. Loop through target_ids (preserving order) and save subsets.
    """
    try:
        # Read the sequence file
        df_seq = pd.read_csv(final_clusters_seq_info, sep="\t")

        # Validate required column exists
        if "clone_clonotype_id" not in df_seq.columns:
            raise ValueError("Input file missing required column: 'clone_clonotype_id'")

        # Create a temporary column for matching logic:
        # Extract '0' from '0_0' matching the logic: split("_")[0]
        df_seq["__match_id"] = (
            df_seq["clone_clonotype_id"].astype(str).str.split("_").str[0]
        )

        # Iterate through the ranking list to maintain the specific order (Rank 1, Rank 2...)
        for rank_index, target_id in enumerate(target_ids):

            # Filter the dataframe for this specific cluster ID
            # We strictly match strings to strings
            subset = df_seq[df_seq["__match_id"] == str(target_id)].copy()

            # Drop the temporary helper column before writing
            subset.drop(columns=["__match_id"], inplace=True)

            # Construct output filename: Name_Rank_seq_info.txt
            # rank_index starts at 0, so we add 1
            file_path = os.path.join(output_dir, f"{rank_index + 1}_seq_info.tsv")

            # Write to TSV, keeping the header, without the pandas index
            subset.to_csv(file_path, sep="\t", index=False)

    except Exception as e:
        print(f"Error processing sequence file: {e}")
        sys.exit(1)


def main():
    start_time = time.time()

    # Using argparse for robust argument handling
    parser = argparse.ArgumentParser(description="Intraclonal Study Input Creator")

    parser.add_argument(
        "-c",
        "--final_clusters_seq_info",
        required=True,
        help="Path to sequence data (TSV with header)",
    )
    parser.add_argument(
        "-r",
        "--repertoire_two_levels_info",
        required=True,
        help="Path to ranking data (TSV without header)",
    )
    parser.add_argument(
        "-o", "--output_dir", required=True, help="Name prefix for output files"
    )
    parser.add_argument(
        "-s",
        "--number_of_clonotype_to_analyze",
        required=True,
        type=int,
        dest="nb_clone",
        help="Number of top clones to analyze",
    )

    args = parser.parse_args()

    # 1. Get the ordered list of Cluster IDs to analyze
    target_ids = get_target_cluster_ids(args.repertoire_two_levels_info, args.nb_clone)

    # 2. Extract sequences and write output files
    if target_ids:
        process_sequences(args.final_clusters_seq_info, target_ids, args.output_dir)

    print(
        "The intraclonal study input creator execution time : %s seconds "
        % (time.time() - start_time)
    )


if __name__ == "__main__":
    main()
