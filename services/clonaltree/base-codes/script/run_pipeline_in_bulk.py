import os
import sys
import argparse
import subprocess
from pathlib import Path


def run_batch_pipeline(directory_path):
    # Convert input to a Path object
    input_dir = Path(directory_path)

    # 1. Check if directory exists
    if not input_dir.is_dir():
        print(f"Error: The directory '{directory_path}' does not exist.")
        sys.exit(1)

    # 2. Check if the pipeline script exists in the current folder
    pipeline_script = "main_pipeline.py"
    if not os.path.exists(pipeline_script):
        print(f"Error: Could not find '{pipeline_script}' in the current folder.")
        sys.exit(1)

    # 3. Gather all TSV files
    tsv_files = list(input_dir.glob("*.tsv"))

    if not tsv_files:
        print(f"No .tsv files found in '{directory_path}'.")
        sys.exit(0)

    print(f"Found {len(tsv_files)} TSV files. Starting sequential processing...\n")

    # 4. Loop through files one by one
    for file_path in tsv_files:
        # Extract the dataset name (filename without extension)
        dataset_name = file_path.stem

        # Get the absolute path of the tsv file to avoid relative path issues
        full_path = str(file_path.resolve())

        print(f"--------------------------------------------------")
        print(f"Processing dataset: {dataset_name}")
        print(f"File: {full_path}")

        # Construct the command
        # using sys.executable ensures we use the same python interpreter
        cmd = [sys.executable, pipeline_script, dataset_name, full_path]

        try:
            # Run the command and wait for it to finish before moving to the next
            subprocess.run(cmd, check=True)
            print(f"Successfully finished: {dataset_name}")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Pipeline failed for {dataset_name}.")
            # Optional: Add 'sys.exit(1)' here if you want to stop the whole loop on error
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    print("\nAll files processed.")


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Run main_pipeline.py for all TSV files in a directory."
    )
    parser.add_argument("directory", help="Path to the directory containing TSV files")

    args = parser.parse_args()

    run_batch_pipeline(args.directory)
