import argparse
import pandas as pd
from pathlib import Path


def parse_gene_call(value):
    """
    Parses gene columns (V, D, J).
    Splits by '|', takes the first element, removes whitespace,
    and prepends 'Homsap'.
    """
    if pd.isna(value):
        return value

    # Ensure string, split by pipe, take first item, strip whitespace
    first_call = str(value).split("|")[0].strip()
    return f"Homsap {first_call}"


def parse_functionality(value):
    """
    Parses functionality/productivity.
    Returns 'T' if the string starts with 'productive', else 'F'.
    """
    if pd.isna(value):
        return "F"

    # Check if the first word is productive
    # .strip() removes surrounding whitespace, then we check start
    return "T" if str(value).strip().lower().startswith("productive") else "F"


def process_csv_files(directory_path):
    target_dir = Path(directory_path)

    if not target_dir.is_dir():
        print(f"Error: The directory '{target_dir}' does not exist.")
        return

    # List of columns we specifically want to process and keep
    # Logic: Mapped keys are old names, values are new names (where simple renaming applies)
    rename_map = {
        "Seq_ID": "sequence_id",
        "Sequence": "sequence",
        "AA JUNCTION": "junction_aa",
        "CDR3.IMGT": "cdr3",
        "AA_CDR3_edited": "cdr3_aa",
        "sequence_alignment": "sequence_alignment",
        "j_sequence_alignment": "j_sequence_alignment",
        "v_sequence_alignment": "v_sequence_alignment",
        "j_sequence_alignment_aa": "j_sequence_alignment_aa",
        "v_sequence_alignment_aa": "v_sequence_alignment_aa",
    }

    # Find all .csv files in the directory
    csv_files = list(target_dir.glob("*.csv"))

    if not csv_files:
        print(f"No CSV files found in {target_dir}")
        return

    print(f"Found {len(csv_files)} CSV files. Starting processing...")

    for file_path in csv_files:
        try:
            # Read the CSV
            df = pd.read_csv(file_path)

            # Create a new DataFrame to store processed data
            # This ensures the final TSV is clean and only contains requested columns
            clean_df = pd.DataFrame()

            # 1. Handle Simple Renames (Data untouched)
            for old_col, new_col in rename_map.items():
                if old_col in df.columns:
                    clean_df[new_col] = df[old_col]

            # 2. Handle "V-DOMAIN Functionality" -> "productive"
            if "V-DOMAIN Functionality" in df.columns:
                clean_df["productive"] = df["V-DOMAIN Functionality"].apply(
                    parse_functionality
                )

            # 3. Handle Gene Calls (V, D, J)
            gene_columns = {
                "V-GENE and allele": "v_call",
                "J-GENE and allele": "j_call",
                "D-GENE and allele": "d_call",
            }

            for old_col, new_col in gene_columns.items():
                if old_col in df.columns:
                    clean_df[new_col] = df[old_col].apply(parse_gene_call)

            # Define output path
            output_filename = f"{file_path.stem}_preprocess.tsv"
            output_path = target_dir / output_filename

            # Save as TSV (Tab Separated Values)
            clean_df.to_csv(output_path, sep="\t", index=False)

            print(f"Successfully created: {output_filename}")

        except Exception as e:
            print(f"Failed to process {file_path.name}: {e}")


if __name__ == "__main__":
    # Argument parser to take directory from command line
    parser = argparse.ArgumentParser(
        description="Process CSV files into AIRR-like TSV format."
    )
    parser.add_argument(
        "directory", type=str, help="Path to the directory containing CSV files"
    )

    args = parser.parse_args()

    process_csv_files(args.directory)
