import argparse
import subprocess
import sys
from pathlib import Path


def run_pipeline(root_directory):
    root_path = Path(root_directory)

    # Define the path to the pipeline script
    # Assuming the script folder is in the current working directory as per your example
    pipeline_script = Path("./script/top_n_clonotype_number.py")

    if not root_path.exists():
        print(f"Error: Directory '{root_directory}' does not exist.")
        sys.exit(1)

    if not pipeline_script.exists():
        print(f"Error: Pipeline script not found at '{pipeline_script}'.")
        sys.exit(1)

    # 1. Iterate over subdirectories (e.g., IGH_by_sample_results_L1_abundance_0)
    for subdir in sorted(root_path.iterdir()):
        if not subdir.is_dir():
            continue

        print(f"Processing directory: {subdir.name}")

        # Generate the specific tag for the output filename based on directory name
        # Example: "IGH_by_sample_results_L1_abundance_0" -> "L1_abundance_0"
        dir_tag = subdir.name.replace("IGH_by_sample_results_", "")

        # 2. Find all 'repertoire' files to identify samples
        # We search for the pattern *_repertoire_two_levels_info.tsv
        repertoire_files = sorted(subdir.glob("*_repertoire_two_levels_info.tsv"))

        for rep_file in repertoire_files:
            # 3. Extract Sample ID
            # Example: "M21_329C-A1_repertoire_two_levels_info.tsv" -> "M21_329C-A1"
            sample_id = rep_file.name.replace("_repertoire_two_levels_info.tsv", "")

            # 4. Construct the expected path for the paired "clusters" file
            query_file = subdir / f"{sample_id}_clusters_seq_info.tsv"

            # Check if the pair exists
            if query_file.exists():
                # 5. Define the Output path
                # Example: M21_329C-A1_L1_abundance_0.tsv
                output_filename = f"{sample_id}_{dir_tag}.tsv"
                output_file = subdir / output_filename

                # 6. Construct the Command
                cmd = [
                    "python",
                    str(pipeline_script),
                    "-s",
                    str(rep_file),
                    "-q",
                    str(query_file),
                    "-o",
                    str(output_file),
                    "-n",
                    "10",
                ]

                # 7. Execute the command (No threading, waits for completion)
                print(f"  -> Running for sample: {sample_id}")
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"  !! Error processing {sample_id}: {e}")
            else:
                print(
                    f"  !! Warning: Missing pair for {sample_id} (Expected {query_file.name})"
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run clonotype pipeline on paired files."
    )
    parser.add_argument(
        "directory", help="Path to the root directory containing sample folders"
    )

    args = parser.parse_args()

    run_pipeline(args.directory)
