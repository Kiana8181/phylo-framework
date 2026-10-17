import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path

from config.path import ROOT_DIR
from config.setting import *


def run_step(cmd, log_file, description, cwd):
    """
    Helper function to run a command and log output to a file.
    """
    print(description)
    cmd = [str(i) for i in cmd]
    try:
        with open(log_file, "+a") as f:
            subprocess.run(
                cmd, stdout=f, stderr=subprocess.STDOUT, check=True, cwd=cwd, text=True
            )
    except subprocess.CalledProcessError as e:
        print(f"Error occurred during: {description}")
        print(f"Check log file for details: {log_file}")
        sys.exit(1)


def safe_remove(file_path):
    try:
        os.remove(file_path)
    except OSError:
        pass


def safe_move(src, dst):
    try:
        shutil.move(src, dst)
    except FileNotFoundError:
        pass
    except shutil.Error:
        pass


def main():
    parser = argparse.ArgumentParser(description="Clonotype clustering pipeline.")
    parser.add_argument("dataset_name", help="Name of the dataset (e.g., sc1_BORJ)")
    parser.add_argument(
        "input_file", help="Path to input file (e.g., data/sc1_BORJ/vquest_airr.tsv)"
    )

    args = parser.parse_args()

    dataset_name = Path(args.dataset_name).name

    # change input file path to absolute path
    input_file = Path(args.input_file).resolve()

    output_base = os.path.join(ROOT_DIR, ".cache", dataset_name)
    os.makedirs(output_base, exist_ok=True)

    log_file = os.path.join(ROOT_DIR, ".cache", dataset_name, "log.txt")

    print("Starting...")
    print(f"Dataset: {dataset_name}")
    print(f"Input: {input_file}")
    print(f"Output: {output_base}")

    # Use current python executable
    python_exe = sys.executable

    # --- Step 1: Format input ---
    cmd = [
        python_exe,
        os.path.join(ROOT_DIR, "src", "format", "format_labeling_imgt_airr.py"),
        "-a",
        input_file,
        "-o",
        output_base,
        "-t",
        ABUNDANCE_THRESHOLD
    ]
    run_step(cmd, log_file, "Step 1: Formatting input...", ROOT_DIR)

    # --- Step 2: Initial clustering ---
    cmd = [
        python_exe,
        os.path.join(ROOT_DIR, "src", "cluster", "initial_clustering.py"),
        "-i",
        os.path.join(output_base, "format_labeling_imgt_airr.tsv"),
        "-o",
        output_base,
        "-t",
        f"{INITIAL_CLUSTERING_THRESHOLD}",
    ]
    run_step(cmd, log_file, "Step 2: Initial clustering...", ROOT_DIR)

    # --- Step 3: Refinement ---
    cmd = [
        python_exe,
        os.path.join(ROOT_DIR, "src", "refinement", "refinement.py"),
        "-f",
        os.path.join(
            ROOT_DIR,
            ".cache",
            dataset_name,
            f"sameVJ_noallele_CDR3_{INITIAL_CLUSTERING_THRESHOLD}.tsv",
        ),
        "-l",
        os.path.join(ROOT_DIR, ".cache", dataset_name, f"initial_clusters_Fo.tsv"),
        "-v",
        V_DISTANCE,
        "-j",
        J_DISTANCE,
        "-c",
        CDR3_DISTANCE,
        "-d",
        COMBINE_DISTANCE,
        "-m",
        MERGE_SINGLETON,
        "-o",
        os.path.join(ROOT_DIR, ".cache", dataset_name),
    ]
    run_step(cmd, log_file, "Step 3: Refinement...", ROOT_DIR)

    # --- Step 4: Two-level hierarchy ---
    cmd = [
        python_exe,
        os.path.join(ROOT_DIR, "src", "cluster", "two_level_clonal_info.py"),
        "-f",
        os.path.join(ROOT_DIR, ".cache", dataset_name, "clone_V_CDR3_J.tsv"),
        "-c",
        os.path.join(ROOT_DIR, ".cache", dataset_name, "final_clusters_Fo.tsv"),
        "-n",
        dataset_name,
        "-m",
        CLONOTYPE_METHOD,
        "-t",
        SIMILARITY_THRESHOLD,
        "-o",
        os.path.join(ROOT_DIR, ".cache", dataset_name),
    ]
    run_step(cmd, log_file, "Step 4: Creating two-level hierarchy...", ROOT_DIR)

    if REMOVE_INTERMEDIATE_FILES:
        safe_remove(os.path.join(output_base, "initial_clusters_Fo.tsv"))
        safe_remove(os.path.join(output_base, "format_labeling_imgt_airr.tsv"))
        safe_remove(
            os.path.join(
                output_base, f"sameVJ_noallele_CDR3_{INITIAL_CLUSTERING_THRESHOLD}.tsv"
            )
        )
        safe_remove(os.path.join(output_base, "final_clusters_Fo.tsv"))
        safe_remove(os.path.join(output_base, "clone_V_CDR3_J.tsv"))
        safe_remove(os.path.join(output_base, "sorted_clusters.p"))

    # --- Step 7: Select top clones for analysis ---
    cmd = [
        python_exe,
        os.path.join(ROOT_DIR, "src", "select_clone", "top_clones.py"),
        "-r",
        os.path.join(output_base, "repertoire_two_levels_info.tsv"),
        "-c",
        os.path.join(output_base, "final_clusters_seq_info.tsv"),
        "-o",
        output_base,
        "-s",
        f"{NUMBER_TOP_CLONE}",
    ]
    run_step(cmd, log_file, "Step 7/8: Selecting top clones...", ROOT_DIR)

    # --- Step 8: Alignment and tree construction ---
    print(f"Step 8/8: Building trees for top {NUMBER_TOP_CLONE} clones...")

    for i in range(1, NUMBER_TOP_CLONE + 1):  # 1 -> NUMBER_TOP_CLONE
        for j in [30, 200]:
            seq_info_file = os.path.join(output_base, f"{i}_seq_info.tsv")

            if os.path.exists(seq_info_file):
                print(f"  Processing clone {i} with {j} clonotypes...")

                # Alignment
                cmd_align = [
                    python_exe,
                    os.path.join(
                        ROOT_DIR, "src", "alignment", "alignment_intraclonal.py"
                    ),
                    "-a",
                    str(input_file),
                    "-f",
                    str(seq_info_file),
                    "-n",
                    os.path.join(output_base, f"{dataset_name}_{i}"),
                    "-s",
                    str(j),
                ]
                try:
                    with open(log_file, "a") as f:
                        subprocess.run(
                            cmd_align,
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            check=True,
                            cwd=ROOT_DIR,
                        )
                except subprocess.CalledProcessError:
                    print(f"Warning: Alignment failed for clone {i} size {j}")
                    continue

                # Tree Construction
                aln_file = os.path.join(
                    output_base, f"{dataset_name}_{i}_{j}_uniq.aln.fa"
                )
                if os.path.exists(aln_file):
                    cmd_tree = [
                        python_exe,
                        os.path.join(ROOT_DIR, "src", "tree", "clonal_tree.py"),
                        "-i",
                        aln_file,
                        "-o",
                        os.path.join(output_base, f"{dataset_name}_{i}_{j}.nk"),
                        "-a",
                        "0",
                        "-r",
                        "0",
                    ]
                    try:
                        with open(log_file, "a") as f:
                            subprocess.run(
                                cmd_tree,
                                stdout=f,
                                stderr=subprocess.STDOUT,
                                check=True,
                                cwd=ROOT_DIR,
                            )
                    except subprocess.CalledProcessError:
                        print(
                            f"Warning: Tree construction failed for clone {i} size {j}"
                        )
                    if REMOVE_INTERMEDIATE_FILES:
                        # Loop Cleanup
                        safe_remove(
                            os.path.join(output_base, f"{dataset_name}_{i}_{j}_all.aln.fa")
                        )
                        safe_remove(
                            os.path.join(
                                output_base, f"{dataset_name}_{i}_{j}_selected_seq.fasta"
                            )
                        )
                        safe_remove(
                            os.path.join(
                                output_base,
                                f"{dataset_name}_{i}_{j}_selected_seq_uniq.aln.fa",
                            )
                        )
                else:
                    raise ValueError(f"{aln_file} must exist but it's not")
            else:
                raise ValueError(f"{seq_info_file} must exist but it's not")

    if REMOVE_INTERMEDIATE_FILES:
        safe_remove(os.path.join(output_base, f"final_clusters_Fo.tsv"))
        safe_remove(os.path.join(output_base, f"final_clusters_seq_info.tsv"))

    print("")
    print(" Pipeline complete!")
    print(f" Results in: {output_base}")
    print(f" Main output: {os.path.join(output_base, 'repertoire_two_levels_info.tsv')}")
    print("")


if __name__ == "__main__":
    main()
