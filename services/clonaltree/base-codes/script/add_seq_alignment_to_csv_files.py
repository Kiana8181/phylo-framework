import os
import argparse
import pandas as pd


def process_files(csv_directory, tsv_file_path):
    # 1. Check if paths exist
    if not os.path.isdir(csv_directory):
        print(f"Error: Directory '{csv_directory}' does not exist.")
        return
    if not os.path.isfile(tsv_file_path):
        print(f"Error: File '{tsv_file_path}' does not exist.")
        return

    print("--- Loading TSV Data ---")
    try:
        # Define the columns we need to grab from the TSV
        # sequence_id is the key, the rest are the data we want to add
        columns_to_extract = [
            "sequence_id",
            "sequence_alignment",
            "j_sequence_alignment",
            "v_sequence_alignment",
            "j_sequence_alignment_aa",
            "v_sequence_alignment_aa",
        ]

        # 2. Read the TSV file
        tsv_df = pd.read_csv(tsv_file_path, sep="\t")

        # Verify that all required columns exist in the TSV
        missing_cols = [col for col in columns_to_extract if col not in tsv_df.columns]
        if missing_cols:
            print(
                f"Error: The TSV file is missing the following required columns: {missing_cols}"
            )
            return

        # Select only the necessary columns
        reference_df = tsv_df[columns_to_extract]

        # Remove potential duplicates in the TSV based on the ID
        reference_df = reference_df.drop_duplicates(subset=["sequence_id"])

        print(f"TSV loaded successfully. Found {len(reference_df)} unique sequences.")

    except Exception as e:
        print(f"Error reading TSV file: {e}")
        return

    print("\n--- Processing CSV Files ---")

    # 3. Iterate through CSV files
    processed_count = 0

    for filename in os.listdir(csv_directory):
        if filename.endswith(".csv"):

            # Skip files that have already been processed
            if "alignment_added" in filename:
                continue

            file_path = os.path.join(csv_directory, filename)
            print(f"Processing: {filename}...")

            try:
                # Read the CSV
                csv_df = pd.read_csv(file_path)

                # Check if Seq_ID exists
                if "Seq_ID" not in csv_df.columns:
                    print(
                        f"  Warning: Skipped '{filename}' - column 'Seq_ID' not found."
                    )
                    continue

                # 4. Merge the data
                # This performs a VLOOKUP-style operation for all columns in reference_df
                merged_df = pd.merge(
                    csv_df,
                    reference_df,
                    left_on="Seq_ID",
                    right_on="sequence_id",
                    how="left",
                )

                # Clean up: Drop the redundant 'sequence_id' from the TSV (since we have Seq_ID)
                if "sequence_id" in merged_df.columns:
                    merged_df.drop(columns=["sequence_id"], inplace=True)

                # 5. Save the file with new name
                name_without_ext = os.path.splitext(filename)[0]
                new_filename = f"{name_without_ext}_alignment_added.csv"
                save_path = os.path.join(csv_directory, new_filename)

                merged_df.to_csv(save_path, index=False)
                processed_count += 1

            except Exception as e:
                print(f"  Error processing '{filename}': {e}")

    print(f"\nDone. Processed {processed_count} files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add alignment columns from TSV to a folder of CSV files."
    )
    parser.add_argument("csv_dir", help="Path to the directory containing CSV files")
    parser.add_argument(
        "tsv_path", help="Path to the TSV file containing sequence data"
    )

    args = parser.parse_args()

    process_files(args.csv_dir, args.tsv_path)
