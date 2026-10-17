import sys
import os
from optparse import OptionParser
import time
import pandas as pd
from pathlib import Path

import Levenshtein

# add project's root to os path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.util import write_tsv, read_tsv


def hamming_similarity(s1, s2):
    """Calculates similarity: (matches / length). Assumes equal length."""
    if len(s1) != len(s2) or len(s1) == 0:
        return 0.0
    matches = sum(c1 == c2 for c1, c2 in zip(s1, s2))
    return matches / len(s1)


def extract_call(call_str, level="gene"):
    """
    Parses string like "Homsap IGHV1-69*01 F" or "IGHV1-69*01".
    Handles the split logic defined in the prompt robustly.
    """
    if pd.isna(call_str) or call_str == "":
        return ""

    # Handle "Species Gene" format vs just "Gene"
    clean_call = call_str.split(" ")[1] if " " in call_str else call_str

    if level == "allele":
        return clean_call  # IGHV1-69*01
    elif level == "gene":
        return clean_call.split("*")[0]  # IGHV1-69
    elif level == "family":
        return clean_call.split("*")[0].split("-")[0]  # IGHV1

    return clean_call


def read_sequence_data(nomFi):
    """
    Reads the Sequence Info TSV.
    """
    try:
        df = read_tsv(nomFi)
    except Exception as e:
        sys.exit(f"Error reading sequence file {nomFi}: {e}")

    required_cols = [
        "sequence_id",
        "productive",
        "v_call",
        "j_call",
        "d_call",
        "cdr3_aa",
        "sequence_alignment",
        "junction_aa",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"Warning: Columns {missing} missing. Some methods may fail.")

    df.set_index("sequence_id", inplace=True)
    seq_dict = df.fillna("").to_dict(orient="index")
    column_order = list(df.columns)

    return seq_dict, column_order


def read_clustering_results(nomFi):
    try:
        df = read_tsv(nomFi)
    except Exception as e:
        sys.exit(f"Error reading clustering file {nomFi}: {e}")

    if "clone_id" not in df.columns or "sequence_ids" not in df.columns:
        sys.exit("Clustering file missing 'clone_id' or 'sequence_ids' columns.")

    Clustering_labels = {}
    for _, row in df.iterrows():
        cluster = str(row["clone_id"])
        seq_list = str(row["sequence_ids"]).split(" ")
        seq_list = [s for s in seq_list if s]

        if cluster in Clustering_labels:
            Clustering_labels[cluster].extend(seq_list)
        else:
            Clustering_labels[cluster] = seq_list

    return Clustering_labels


def group_sequences_by_method(seq_list, dicoSeq, method, threshold):
    """
    Input: List of sequence IDs belonging to ONE Clone.
    Output: Dictionary { 'Representative_Key': [List of IDs] }
    """

    # ---------------- L1: Strict (Sequence Alignment) ----------------
    if method == "L1":
        groups = {}
        for s in seq_list:
            # Key is the full nucleotide sequence
            key = dicoSeq[s].get("sequence_alignment", "")
            if key not in groups:
                groups[key] = []
            groups[key].append(s)
        return groups

    # ---------------- L2: IMGT (Alleles + Anchors) ----------------
    elif method == "L2":
        groups = {}
        for s in seq_list:
            row = dicoSeq[s]
            junction = row.get("junction_aa", "")

            # Pre-Check Anchors
            if not (junction.startswith("C") and junction.endswith(("W", "F"))):
                continue  # Exclude Out of Frame / Invalid Anchors

            v_allele = extract_call(row.get("v_call", ""), "allele")
            d_allele = extract_call(row.get("d_call", ""), "allele")
            j_allele = extract_call(row.get("j_call", ""), "allele")

            # Key includes Alleles and Exact Junction
            key = f"{v_allele}|{d_allele}|{j_allele}|{junction}"

            if key not in groups:
                groups[key] = []
            groups[key].append(s)
        return groups

    # ---------------- L3: B-DIVE (Fam + CDR3) ----------------
    elif method == "L3":
        groups = {}
        for s in seq_list:
            row = dicoSeq[s]
            v_fam = extract_call(row.get("v_call", ""), "family")
            j_fam = extract_call(row.get("j_call", ""), "family")
            cdr3 = row.get("cdr3_aa", "")

            key = f"{v_fam}|{j_fam}|{cdr3}"

            if key not in groups:
                groups[key] = []
            groups[key].append(s)
        return groups

    # ---------------- L4: Similarity (Gene + Levenshtein) ----------------
    elif method == "L4":
        # Greedy Clustering
        # 1. Pre-calculate genes to avoid re-parsing
        temp_data = []
        for s in seq_list:
            row = dicoSeq[s]
            v_gene = extract_call(row.get("v_call", ""), "gene")
            cdr3 = row.get("cdr3_aa", "")
            if cdr3:  # Only cluster if CDR3 exists
                temp_data.append({"id": s, "v": v_gene, "cdr3": cdr3})

        groups = {}

        while temp_data:
            # Pick a center (first available)
            center = temp_data.pop(0)
            center_key = f"{center['v']}_{center['cdr3']}"  # Use center as key

            if center_key in groups:
                # Handle edge case where center key duplicates
                # Just append to existing (though strictly greedy usually isolates)
                current_group_ids = groups[center_key]
            else:
                current_group_ids = [center["id"]]
                groups[center_key] = current_group_ids

            # Find neighbors in remaining list
            ungrouped_next = []
            for candidate in temp_data:
                # 1. Check Gene
                if candidate["v"] != center["v"]:
                    ungrouped_next.append(candidate)
                    continue

                # 2. Check Similarity
                dist = Levenshtein.distance(center["cdr3"], candidate["cdr3"])
                max_len = max(len(center["cdr3"]), len(candidate["cdr3"]))
                if max_len == 0:
                    sim = 0
                else:
                    sim = 1.0 - (dist / max_len)

                if sim >= threshold:
                    current_group_ids.append(candidate["id"])
                else:
                    ungrouped_next.append(candidate)

            temp_data = ungrouped_next

        return groups

    # ---------------- L5: Length + Similarity (Gene + Hamming) ----------------
    elif method == "L5":
        temp_data = []
        for s in seq_list:
            row = dicoSeq[s]
            v_gene = extract_call(row.get("v_call", ""), "gene")
            cdr3 = row.get("cdr3_aa", "")
            if cdr3:
                temp_data.append({"id": s, "v": v_gene, "cdr3": cdr3})

        groups = {}

        while temp_data:
            center = temp_data.pop(0)
            center_key = f"{center['v']}_{center['cdr3']}"

            if center_key in groups:
                current_group_ids = groups[center_key]
            else:
                current_group_ids = [center["id"]]
                groups[center_key] = current_group_ids

            ungrouped_next = []
            for candidate in temp_data:
                # 1. Check Gene
                if candidate["v"] != center["v"]:
                    ungrouped_next.append(candidate)
                    continue

                # 2. Check Length STRICTLY
                if len(candidate["cdr3"]) != len(center["cdr3"]):
                    ungrouped_next.append(candidate)
                    continue

                # 3. Hamming Similarity
                sim = hamming_similarity(center["cdr3"], candidate["cdr3"])

                if sim >= threshold:
                    current_group_ids.append(candidate["id"])
                else:
                    ungrouped_next.append(candidate)

            temp_data = ungrouped_next

        return groups

    else:
        sys.exit(f"Unknown method {method}")


def calculate_abundance(list_of_occurance):
    sum_all = 0
    abundance = []
    for clonotype in list_of_occurance:
        occurance = clonotype[0]
        sum_all += occurance

    for clonotype in list_of_occurance:
        occurance = clonotype[0]
        functionality = clonotype[1]
        CDR3 = clonotype[2]
        if sum_all > 0:
            val = occurance / float(sum_all)
        else:
            val = 0
        abundance.append(("%.5f" % val, functionality, CDR3))
    return abundance


def gather_clone_clonotype_info(Dicoresult, dicoSeq, method, threshold):
    """
    Aggregates sequences into Clones and Clonotypes based on the selected Method.
    Fixed to handle cases where grouping methods (like L2) filter out all sequences in a clone.
    """
    clonotypes = {}
    clonal_info = {}

    total_sequences = len(dicoSeq)

    for c in Dicoresult.keys():
        seq_list = Dicoresult[c]

        # Filter valid sequences (must exist in sequence file)
        valid_seqs = [s for s in seq_list if s in dicoSeq]
        if not valid_seqs:
            continue

        # 1. Group sequences within this clone using the selected method
        # This returns { 'group_key': [seq_id_1, seq_id_2...] }
        grouped_clonotypes = group_sequences_by_method(
            valid_seqs, dicoSeq, method, threshold
        )

        # If method (e.g. L2) filtered out all sequences (e.g. no valid anchors), skip this clone
        if not grouped_clonotypes:
            continue

        # Check total sequences after grouping
        total_grouped_seqs = sum(len(v) for v in grouped_clonotypes.values())
        if total_grouped_seqs == 0:
            continue

        # NOW it is safe to populate the dictionaries
        clonotypes[c] = grouped_clonotypes

        clone_abundance = total_grouped_seqs / float(total_sequences)
        read_count = total_grouped_seqs

        # Clone V/J (First valid seq)
        first_group_key = list(grouped_clonotypes.keys())[0]
        first_seq_id = grouped_clonotypes[first_group_key][0]

        v_gene = dicoSeq[first_seq_id]["v_call"]
        j_gene = dicoSeq[first_seq_id]["j_call"]

        # Initialize info list [Abundance, Count, V, J]
        clonal_info[c] = [("%.5f" % clone_abundance), read_count, v_gene, j_gene]

        # Add representative CDR3s (Legacy requirement)
        for group_key in grouped_clonotypes:
            rep_seq = grouped_clonotypes[group_key][0]
            rep_cdr3 = dicoSeq[rep_seq]["cdr3_aa"]
            clonal_info[c].append(rep_cdr3)

    for clone in clonal_info.keys():
        list_clonotypes = []

        # We are guaranteed that 'clone' exists in clonotypes because we set them together above
        for group_key in clonotypes[clone].keys():
            seqs_in_group = clonotypes[clone][group_key]

            # Rep seq stats
            first_s = seqs_in_group[0]
            func = dicoSeq[first_s]["productive"]
            cdr3_label = dicoSeq[first_s]["cdr3_aa"]

            count = len(seqs_in_group)
            list_clonotypes.append((count, func, cdr3_label))

        # Append abundance calculations
        clonal_info[clone].append(calculate_abundance(list_clonotypes))

    return clonal_info, clonotypes


def write_clonal_info(
    clonal_info_dico_unsorted, clonotype_dico, dicoSeq, output_path
):
    file_path = os.path.join(output_path, "repertoire_two_levels_info.tsv")
    try:
        filetowrite = open(file_path, "w")
    except IOError:
        sys.exit(f"Could not write to file {file_path}")

    # Sort clones by Abundance (Index 0)
    clonal_info_dico = dict(
        sorted(
            clonal_info_dico_unsorted.items(),
            key=lambda t: float(t[1][0]),
            reverse=True,
        )
    )

    for clone in clonal_info_dico.keys():
        phrase_2 = ""
        phrase = (
            "Clone number "
            + str(clone)
            + "\t"
            + str(clonal_info_dico[clone][0])
            + "\t"
            + str(clonal_info_dico[clone][1])
            + "\t"
            + "Clonotype"
        )

        # Prepare list of clonotype groups with their stats for sorting
        # We build a list of dicts: {'freq': float, 'func': str, 'cdr3': str, 'rep_id': str}

        group_objs = []
        total_seqs_in_clone = sum(len(v) for v in clonotype_dico[clone].values())

        for key, seq_list in clonotype_dico[clone].items():
            rep_id = seq_list[0]
            count = len(seq_list)
            freq = count / float(total_seqs_in_clone) if total_seqs_in_clone > 0 else 0

            # Retrieve details from dicoSeq
            seq_data = dicoSeq[rep_id]
            func = seq_data["productive"]
            cdr3 = seq_data["cdr3_aa"]

            group_objs.append(
                {"freq": freq, "func": func, "cdr3": cdr3, "rep_id": rep_id}
            )

        # Sort by Frequency Descending
        sorted_groups = sorted(group_objs, key=lambda x: x["freq"], reverse=True)

        for obj in sorted_groups:
            # Phrase part 1: Frequency, Functionality
            phrase += " " + ("%.5f" % obj["freq"]) + "," + str(obj["func"])

            # Phrase part 2: CDR3, RepID
            phrase_2 += obj["cdr3"] + "," + str(obj["rep_id"]) + " "

        # Add V and J gene info (Indices 2 and 3 in the main list)
        phrase += (
            "\t"
            + str(clonal_info_dico[clone][2])
            + "\t"
            + str(clonal_info_dico[clone][3])
            + "\t"
        )

        phrase_2 = phrase_2[:-1]
        phrase += phrase_2
        phrase += "\n"

        filetowrite.write(phrase)

    filetowrite.close()
    return 0


def add_clone_clonotype_to_seq_info(clonotype_dico, dicoSeq, column_order, output_path):
    file_path = os.path.join(output_path, "final_clusters_seq_info.tsv")
    try:
        filetowrite = open(file_path, "w")
    except IOError:
        sys.exit(f"Could not write to file {file_path}")

    header = "clone_clonotype_id\tsequence_id\t" + "\t".join(column_order) + "\n"
    filetowrite.write(header)

    for clone in clonotype_dico.keys():
        clonotype_number = 0
        # Iterate over groups
        for key in clonotype_dico[clone].keys():
            for seq_id in clonotype_dico[clone][key]:
                unique_id = str(clone) + "_" + str(clonotype_number)
                seq_data = dicoSeq[seq_id]
                line_parts = [unique_id, str(seq_id)]
                for col in column_order:
                    line_parts.append(str(seq_data.get(col, "")))
                phrase = "\t".join(line_parts) + "\n"
                filetowrite.write(phrase)
            clonotype_number += 1

    filetowrite.close()
    return 0


def main():
    start_time = time.time()
    usage = "usage: %prog -f sequence_data.tsv -c clustering_results.tsv -n repertoire_name -m [L1,L2,L3,L4,L5]"
    parser = OptionParser(usage)

    parser.add_option(
        "-f",
        "--formatted_IMGT_annotation_output",
        dest="IMGT_seq_info",
        help="Input Sequence Data (TSV with header)",
    )
    parser.add_option(
        "-c",
        "--ClusteringFile",
        dest="ClusteringFile",
        help="Input Clustering Results (TSV with header)",
    )
    parser.add_option(
        "-n", "--repertoire_name", dest="repertoire_name", help="Output prefix name"
    )

    parser.add_option(
        "-m",
        "--method",
        dest="method",
        default="L3",
        help="Clonotype Definition Method: L1(Strict), L2(IMGT), L3(B-DIVE/Default), L4(Sim), L5(Len+Sim)",
    )
    parser.add_option(
        "-t",
        "--threshold",
        dest="threshold",
        default="0.8",
        help="Similarity threshold for L4 and L5 (default 0.8)",
    )
    parser.add_option(
        "-o",
        "--output",
        dest="output_path",
        help="Output path of the program.",
    )

    options, _ = parser.parse_args()

    # Validation
    if (
        not options.IMGT_seq_info
        or not options.ClusteringFile
        or not options.repertoire_name
    ):
        parser.error("Incorrect number of arguments. Requires -f, -c, and -n.")

    valid_methods = ["L1", "L2", "L3", "L4", "L5"]
    if options.method not in valid_methods:
        parser.error(f"Method must be one of {valid_methods}")

    try:
        threshold = float(options.threshold)
    except ValueError:
        parser.error("Threshold must be a float (e.g., 0.8)")

    IMGT_seq_info = options.IMGT_seq_info
    ClusteringFile = options.ClusteringFile
    repertoire_name = options.repertoire_name
    method = options.method

    print(f"Reading Sequence Data...")
    dico_seq, column_order = read_sequence_data(IMGT_seq_info)

    print("Reading Clustering Results...")
    dico_result = read_clustering_results(ClusteringFile)

    print(f"Processing Clonotypes using Method {method}...")
    # Modified to accept method and threshold
    clonal_info_dico, clonotype_dico = gather_clone_clonotype_info(
        dico_result, dico_seq, method, threshold
    )

    print("Writing Output 1 (Repertoire Info)...")
    # Modified to pass dico_seq for accurate Representative lookups
    write_clonal_info(
        clonal_info_dico, clonotype_dico, dico_seq, options.output_path
    )

    print("Writing Output 2 (Detailed Sequence Info)...")
    add_clone_clonotype_to_seq_info(
        clonotype_dico, dico_seq, column_order, options.output_path
    )

    print("Execution time : %s seconds " % (time.time() - start_time))


if __name__ == "__main__":
    main()
