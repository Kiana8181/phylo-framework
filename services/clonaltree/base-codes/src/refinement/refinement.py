import sys
import time
import pandas as pd
import argparse
from pathlib import Path
from collections import defaultdict
import os
import Levenshtein

# add project's root to os path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from distances import *
from src.util import read_tsv, write_tsv

# Distance library is not refactored, we need these for the functions in this library.
indS = {
    "Productivity": 0,
    "V_label": 1,
    "J_label": 2,
    "CDR3_AA": 3,
    "J_seq_nuc": 4,
    "V_seq_nuc": 5,
    "J_seq_AA": 6,
    "V_seq_AA": 7,
}


def identify_duplicates(df: pd.DataFrame):
    """
    Identify duplicates (identical sequences based on V, J, and CDR3).
    """
    subset_cols = ["v_call", "j_call", "cdr3_aa"]

    # Create the unique df
    unique_df = df.drop_duplicates(subset=subset_cols, keep="first").copy()

    # Create the mapping dictionary
    grouped_ids = df.groupby(subset_cols, sort=False)["sequence_id"].agg(list)

    # First occurrence item is key, the rest are values
    unique_seq_map = {ids[0]: ids[1:] for ids in grouped_ids}

    return unique_seq_map, unique_df


def prepare_vjunction_data(unique_df: pd.DataFrame):
    """
    Transform pd dataframe into dictionary required for calling distance library functions.
    """
    cols_of_interest = [
        "productive",
        "v_call",
        "j_call",
        "cdr3_aa",
        "j_sequence_alignment",
        "v_sequence_alignment",
        "j_sequence_alignment_aa",
        "v_sequence_alignment_aa",
    ]

    subset_df = unique_df[cols_of_interest].astype(str)

    # Handle edge case where max() throws error on empty dataframe
    if subset_df.empty:
        return {}, (0, 0, 0)

    len_max_CDR3 = int(subset_df["cdr3_aa"].str.len().max())
    len_max_J = int(subset_df["j_call"].str.len().max())
    len_max_V = int(subset_df["v_call"].str.len().max())

    keys = unique_df["sequence_id"].astype(str)
    values = subset_df.values.tolist()

    seq_data = dict(zip(keys, values))

    return seq_data, (len_max_CDR3, len_max_J, len_max_V)


def filter_clustering_output(clone_to_seq_ids_map, unique_seq_map):
    """
    Filter duplicates (identical sequences) from clustering output.
    Returns a dictionary with only representative sequences.
    """
    filtered_map = {}
    for cluster_id, seq_list in clone_to_seq_ids_map.items():
        # Keep only sequences that exist in the unique map
        valid_seqs = [seq for seq in seq_list if seq in unique_seq_map]

        # Only add the cluster if it still has sequences
        if valid_seqs:
            filtered_map[cluster_id] = valid_seqs

    return filtered_map


def calculate_cdr3_medoid(seq_data, clone_to_unique_seq_ids_map):
    clone_id_to_cdr3_medoid = {}
    cdr3_idx = indS["CDR3_AA"]

    for cluster_id, seq_ids in clone_to_unique_seq_ids_map.items():
        # Build list of CDR3 strings using list comprehension
        cdr3_list = [seq_data[seq][cdr3_idx] for seq in seq_ids if seq in seq_data]

        if cdr3_list:
            clone_id_to_cdr3_medoid[cluster_id] = Levenshtein.median(cdr3_list)

    return clone_id_to_cdr3_medoid


def find_cluster_nearest_neighbor(clone_id_to_cdr3_medoid):
    """
    Find the nearest neighbor (closest Levenshtein distance) for each cluster centroid.
    """
    cluster_items = list(clone_id_to_cdr3_medoid.items())
    n = len(cluster_items)
    neighbor_map = {}

    if n < 2:
        return {}

    for i in range(n):
        id_i, cdr3_medoid_i = cluster_items[i]

        min_dist = float("inf")
        closest_id = ""
        for j in range(n):
            if i == j:
                continue

            id_j, cdr3_medoid_j = cluster_items[j]

            dist_i_j = Levenshtein.distance(cdr3_medoid_i, cdr3_medoid_j)

            if dist_i_j < min_dist:
                min_dist = dist_i_j
                closest_id = id_j

                if min_dist == 0:
                    break

        neighbor_map[id_i] = str(closest_id)

    return neighbor_map


def merge_cluster(current_clone_to_unique_seq_ids_map, inconsistencies):
    """
    Merges clusters based on inconsistency pairs.
    Prioritizes pairs with the highest number of inconsistencies.
    """
    merged_clusters = {k: v[:] for k, v in current_clone_to_unique_seq_ids_map.items()}

    # Use a set for O(1) lookup speed when checking if a cluster is already merged
    processed = set()

    sorted_merges = sorted(inconsistencies.items(), key=lambda x: x[1], reverse=True)

    for key, _ in sorted_merges:
        id_src, id_dest = key.split("-")

        # Only proceed if neither cluster has been touched in this pass
        if (
            id_src not in processed
            and id_dest not in processed
            and id_src in merged_clusters
            and id_dest in merged_clusters
        ):

            # move sequences from Source to Destination
            merged_clusters[id_dest].extend(merged_clusters[id_src])

            # Remove the Source cluster
            del merged_clusters[id_src]

            processed.add(id_src)
            processed.add(id_dest)

    return merged_clusters


def run_refinement(
    seq_data,
    clone_id_to_cdr3_medoid,
    clone_to_unique_seq_ids_map,
    neighbor_map,
    max_lens,
    type_distance,
    max_iterations,
):
    """
    Iteratively refines clone_to_unique_seq_ids_map by merging inconsistent groups until convergence
    or maximum iterations reached.
    """
    current_clone_to_unique_seq_ids_map = clone_to_unique_seq_ids_map
    current_neighbor_map = neighbor_map
    current_clone_id_to_cdr3_medoid = clone_id_to_cdr3_medoid

    for i in range(max_iterations):
        # Find clones that should be merged based on their nearest neighbor
        inconsistencies = find_inconsistence(
            seq_data,
            current_clone_to_unique_seq_ids_map,
            current_neighbor_map,
            max_lens,
            type_distance,
        )

        if not inconsistencies:
            print(f"refinement: run_refinement: Converged after {i} iterations.")
            break

        current_clone_to_unique_seq_ids_map = merge_cluster(
            current_clone_to_unique_seq_ids_map,
            inconsistencies,
        )

        # Recalculate medoids
        current_clone_id_to_cdr3_medoid = calculate_cdr3_medoid(
            seq_data, current_clone_to_unique_seq_ids_map
        )

        if not current_clone_id_to_cdr3_medoid:
            break

        current_neighbor_map = find_cluster_nearest_neighbor(
            current_clone_id_to_cdr3_medoid
        )

    return (
        current_clone_to_unique_seq_ids_map,
        current_neighbor_map,
        current_clone_id_to_cdr3_medoid,
    )


def check_cdr3_length(seq_data, seq1_id, seq2_id):
    # Cache the column index to avoid repeated dictionary lookups
    col_idx = indS["CDR3_AA"]

    val1 = seq_data[seq1_id][col_idx]
    val2 = seq_data[seq2_id][col_idx]

    return len(val1.split(" ", 1)[0]) == len(val2.split(" ", 1)[0])


def merge_singletons(
    seq_data, clone_to_unique_seq_ids_map, neighbor_map, max_lens, type_distance
):
    """
    Iterates through singleton clusters and attempts to merge them into neighbors
    based on uniformity and distance conditions.
    """

    # Identify candidates upfront.
    singleton_candidates = [
        k for k, v in clone_to_unique_seq_ids_map.items() if len(v) == 1
    ]

    for cluster_id in singleton_candidates:
        # Check if the cluster still exists
        if cluster_id not in clone_to_unique_seq_ids_map:
            continue

        if cluster_id not in neighbor_map:
            continue

        seqs = clone_to_unique_seq_ids_map[cluster_id]

        # Ensure it is still a singleton (safety check)
        if len(seqs) != 1:
            continue

        singleton_seq = seqs[0]

        # Find the best candidate to merge into
        _, to_move, target_id = computeInterClonesDistance(
            seq_data,
            clone_to_unique_seq_ids_map,
            neighbor_map,
            cluster_id,
            singleton_seq,
            max_lens,
            type_distance,
        )

        if target_id not in clone_to_unique_seq_ids_map:
            continue

        target_seqs = clone_to_unique_seq_ids_map[target_id]

        # Check Uniformity Logic
        uni_before = compute_uniformity(seq_data, target_seqs, max_lens, type_distance)

        # Calculate 'after' score
        uni_after = compute_uniformity(
            seq_data, target_seqs + [singleton_seq], max_lens, type_distance
        )

        diff = uni_after - uni_before

        # Final Condition Check
        if (
            diff <= 0.05
            and uni_after < 0.1
            and check_cdr3_length(seq_data, singleton_seq, to_move)
        ):

            # Apply the merge
            clone_to_unique_seq_ids_map[target_id].append(singleton_seq)
            del clone_to_unique_seq_ids_map[cluster_id]

            # Update Medoids and Neighbors
            new_centroids = calculate_cdr3_medoid(seq_data, clone_to_unique_seq_ids_map)
            neighbor_map = find_cluster_nearest_neighbor(new_centroids)

    return clone_to_unique_seq_ids_map


def find_inconsistence(
    seq_data, clone_to_unique_seq_ids_map, neighbor_map, max_lens, type_distance
):
    """
    Identifies sequences that are closer to a neighboring cluster than their own.
    Returns a dictionary counting these inconsistencies per cluster pair.
    """
    inconsistence = defaultdict(int)
    cdr3_idx = indS["CDR3_AA"]

    for cluster_id, seq_ids in clone_to_unique_seq_ids_map.items():
        if cluster_id not in neighbor_map:
            continue

        for seq_id in seq_ids:
            # Calculate distance to own cluster (Intra)
            dist_intra = computeIntraClonalDistance(
                seq_data,
                clone_to_unique_seq_ids_map,
                cluster_id,
                seq_id,
                max_lens,
                type_distance,
            )

            # Calculate distance to nearest neighbor cluster (Inter)
            dist_inter, neighbor_seq_id, neighbor_cluster_id = (
                computeInterClonesDistance(
                    seq_data,
                    clone_to_unique_seq_ids_map,
                    neighbor_map,
                    cluster_id,
                    seq_id,
                    max_lens,
                    type_distance,
                )
            )

            if dist_inter < dist_intra:
                cdr3_self = seq_data[seq_id][cdr3_idx]
                cdr3_neighbor = seq_data[neighbor_seq_id][cdr3_idx]

                if len(cdr3_self.split()[0]) == len(cdr3_neighbor.split()[0]):

                    key = f"{cluster_id}-{neighbor_cluster_id}"
                    inconsistence[key] += 1

    return dict(inconsistence)


def compute_uniformity(seq_data, target_seqs, max_lens, type_distance):
    n = len(target_seqs)
    # Early exit for singletons or empty lists
    if n <= 1:
        return 0.0

    densities = local_density(seq_data, target_seqs, max_lens, type_distance)

    # Calculate average
    return sum(densities) / n


def local_density(seq_data, target_seqs, max_lens, type_distance):
    """
    Returns a list containing the distance to the nearest neighbor
    for each sequence in target_seqs.
    """
    # Use list comprehension for the outer loop.
    # Use a generator expression inside min() to avoid creating intermediate lists.
    return [
        min(
            computeDistance(seq_data, seq1, seq2, max_lens, type_distance)
            for seq2 in target_seqs
            if seq1 != seq2
        )
        for seq1 in target_seqs
    ]


def write_clone_output_pandas(
    clone_to_unique_map, unique_seq_map, original_df, output_dir
):
    """
    Write the final results to a TSV file including all original columns.
    Renumbers clone_id sequentially starting from 0.
    """
    # Build the Sequence ID -> New Cluster ID map efficiently
    seq_to_cluster_map = {}

    for new_id, seq_list in enumerate(clone_to_unique_map.values()):
        for seq_id in seq_list:
            # Map representative sequence
            seq_to_cluster_map[str(seq_id)] = new_id

            duplicates = unique_seq_map.get(seq_id)
            if duplicates:
                for dup_id in duplicates:
                    seq_to_cluster_map[str(dup_id)] = new_id

    # Prepare the DataFrame
    final_df = original_df.copy()

    # Ensure join keys are strings
    final_df["sequence_id"] = final_df["sequence_id"].astype(str)

    # Map the new clone IDs
    final_df["clone_id"] = final_df["sequence_id"].map(seq_to_cluster_map)

    # Filter and Clean
    # Drop sequences that were filtered out (NaN clone_ids)
    final_df.dropna(subset=["clone_id"], inplace=True)

    # Convert to integer (safe now that NaNs are gone)
    final_df["clone_id"] = final_df["clone_id"].astype(int)

    # Reorder Columns
    cols = list(final_df.columns)
    if "clone_id" in cols:
        cols.insert(0, cols.pop(cols.index("clone_id")))
        final_df = final_df[cols]

    # Write Main Output
    file_path = os.path.join(output_dir, "clone_V_CDR3_J.tsv")
    write_tsv(final_df, file_path)

    # Group by clone_id and join sequence_ids with a space
    clone_to_seq_ids = (
        final_df.groupby("clone_id")["sequence_id"]
        .agg(" ".join)
        .reset_index(name="sequence_ids")
    )

    write_tsv(clone_to_seq_ids, os.path.join(output_dir, "final_clusters_Fo.tsv"))
    return 0


def main():
    start_time = time.time()
    parser = argparse.ArgumentParser(
        description="Refinement script for clustering results."
    )

    parser.add_argument("-f", "--fasta_file", dest="fasta_file", required=True)
    parser.add_argument(
        "-l", "--clustering_file", dest="clustering_file", required=True
    )
    parser.add_argument(
        "-v",
        "--v_distance",
        dest="v_distance",
        required=True,
        help="method for calculating the V gene distance",
    )
    parser.add_argument(
        "-j",
        "--j_distance",
        dest="j_distance",
        required=True,
        help="method for calculating the J gene distance",
    )
    parser.add_argument(
        "-c",
        "--cdr3_distance",
        dest="cdr3_distance",
        required=True,
        help="method for calculating the CDR3 region distance",
    )
    parser.add_argument(
        "-d",
        "--combine_distance",
        dest="combine_distance",
        required=True,
        help="method for combining three distances",
    )
    parser.add_argument(
        "-m",
        "--merge_singleton",
        dest="merge_singleton",
        required=True,
        help="merging the singletons",
    )
    parser.add_argument(
        "-o", "--output", dest="output_dir", required=True, help="output directory"
    )

    args = parser.parse_args()

    fasta_file = args.fasta_file
    output_dir = args.output_dir
    clustering_file = args.clustering_file
    v_distance = args.v_distance
    j_distance = args.j_distance
    cdr3_distance = args.cdr3_distance
    combine_distance = args.combine_distance
    merge_singleton = args.merge_singleton

    # Refinement Iterations
    iterations = 10

    type_distance = (v_distance, cdr3_distance, j_distance, combine_distance)

    df_fasta = read_tsv(fasta_file).fillna("")

    # Filter sequences that lack J alignment, V alignment, or CDR3.
    # Empty strings in 'j_sequence_alignment' cause ZeroDivisionError in distances.py
    cols_to_check = ["j_sequence_alignment", "v_sequence_alignment", "cdr3_aa"]
    existing_cols = [c for c in cols_to_check if c in df_fasta.columns]

    if existing_cols:
        # Keep rows where length of these columns is > 0
        mask = (
            df_fasta[existing_cols]
            .astype(str)
            .apply(lambda x: x.str.strip().str.len() > 0)
            .all(axis=1)
        )

        n_dropped = len(df_fasta) - mask.sum()
        if n_dropped > 0:
            print(
                f"Refinement Warning: Dropped {n_dropped} sequences due to missing V/J alignment or CDR3 to prevent division by zero."
            )
            df_fasta = df_fasta[mask].copy()

    if df_fasta.empty:
        print("Error: No valid sequences remaining after filtering missing alignments.")
        sys.exit(1)

    # duplicate ref: ['v_call', 'j_call', 'cdr3_aa']
    unique_seq_map, unique_df = identify_duplicates(df_fasta)

    # seq_V_CDR3_J, (len_max_CDR3, len_max_J, len_max_V)
    seq_data, max_lens = prepare_vjunction_data(unique_df)

    clone_seq_ids_df = read_tsv(clustering_file)
    clone_seq_ids_df["clone_id"] = clone_seq_ids_df["clone_id"].astype(str)
    # dict: clone_id -> list containing of all sequence_ids
    clone_to_seq_ids_map = (
        clone_seq_ids_df.set_index("clone_id")["sequence_ids"].str.split().to_dict()
    )

    # return a mapping between a clone_id to unique sequence ids of that clone_id
    clone_to_unique_seq_ids_map = filter_clustering_output(
        clone_to_seq_ids_map, unique_seq_map
    )

    # find the medoid of cdr3s for each clone_id
    clone_id_to_cdr3_medoid = calculate_cdr3_medoid(
        seq_data, clone_to_unique_seq_ids_map
    )

    # find the nearest neighbor of each clone_id
    neighbor_map = find_cluster_nearest_neighbor(clone_id_to_cdr3_medoid)

    # refinement main logic
    clone_to_unique_seq_ids_map, neighbor_map, clone_id_to_cdr3_medoid = run_refinement(
        seq_data,
        clone_id_to_cdr3_medoid,
        clone_to_unique_seq_ids_map,
        neighbor_map,
        max_lens,
        type_distance,
        iterations,
    )

    if merge_singleton == "1":
        clone_to_unique_seq_ids_map = merge_singletons(
            seq_data, clone_to_unique_seq_ids_map, neighbor_map, max_lens, type_distance
        )

    write_clone_output_pandas(
        clone_to_unique_seq_ids_map, unique_seq_map, df_fasta, output_dir
    )

    print(
        "The refinement step execution time : %s seconds " % (time.time() - start_time)
    )


if __name__ == "__main__":
    main()
