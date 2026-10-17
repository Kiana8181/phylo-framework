import csv
import argparse
import sys
from typing import Dict, List

csv.field_size_limit(sys.maxsize)


def parse_arguments():
    """Handles command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="Extract clone statistics and calculate clonotype counts."
    )
    parser.add_argument(
        "-s",
        "--stats",
        required=True,
        help="Path to the statistics TSV file (no header)",
    )
    parser.add_argument(
        "-q",
        "--seqs",
        required=True,
        help="Path to the sequences TSV file (header present)",
    )
    parser.add_argument(
        "-o", "--output", required=True, help="Path to the output TSV file"
    )
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        required=True,
        help="Number of top clones to analyze",
    )
    return parser.parse_args()


def get_top_clones(file_path: str, n: int) -> List[int]:
    """
    Reads the first N lines of the stats file to get Clone IDs.
    Returns a list to maintain rank order.
    """
    top_clones = []

    try:
        with open(file_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")

            for i, row in enumerate(reader):
                if i >= n:
                    break

                # Expecting format: "Clone number 1330" in the first column
                try:
                    clone_str = row[0]
                    # Split by space and take the last part ("1330")
                    clone_id = int(clone_str.split()[-1])
                    top_clones.append(clone_id)
                except (ValueError, IndexError):
                    print(
                        f"Warning: Could not parse line {i+1} in stats file.",
                        file=sys.stderr,
                    )
                    continue

    except FileNotFoundError:
        print(f"Error: Stats file not found at '{file_path}'", file=sys.stderr)
        sys.exit(1)

    return top_clones


def find_clonotype_counts(
    seq_file_path: str, target_clones: List[int]
) -> Dict[int, int]:
    """
    Scans the sequence file to find the max clonotype ID for the target clones.
    """
    # Use a set for O(1) lookup speed
    target_set = set(target_clones)

    # Initialize dictionary: {clone_id: current_max_clonotype_id}
    # We init to -1. If max found is 0, count becomes 1. If not found, count is 0.
    max_indices = {cid: -1 for cid in target_set}

    try:
        with open(seq_file_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                try:
                    # Column format: "cloneId_clonotypeId" (e.g., "1330_5")
                    full_id = row["clone_clonotype_id"]

                    # Manual split is often faster than regex for simple delimiters
                    sep_index = full_id.find("_")
                    if sep_index == -1:
                        continue

                    c_id = int(full_id[:sep_index])

                    # Efficiency: Skip row immediately if not a top N clone
                    if c_id not in target_set:
                        continue

                    ct_id = int(full_id[sep_index + 1 :])

                    if ct_id > max_indices[c_id]:
                        max_indices[c_id] = ct_id

                except (ValueError, KeyError):
                    continue

    except FileNotFoundError:
        print(f"Error: Sequence file not found at '{seq_file_path}'", file=sys.stderr)
        sys.exit(1)

    # Calculate final counts (max_index + 1)
    results = {}
    for cid, max_idx in max_indices.items():
        results[cid] = max_idx + 1 if max_idx != -1 else 0

    return results


def write_output(output_path: str, ranked_ids: List[int], results: Dict[int, int]):
    """Writes the results to a TSV file."""
    try:
        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")

            # Writing Header
            writer.writerow(["Rank", "Clone_ID", "Clonotype_Count"])

            # Writing Data in original rank order
            for rank, cid in enumerate(ranked_ids, 1):
                count = results.get(cid, 0)
                writer.writerow([rank, cid, count])

        print(f"Success! Processed {len(ranked_ids)} clones.")
        print(f"Output saved to: {output_path}")

    except IOError as e:
        print(f"Error writing to output file: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    args = parse_arguments()

    # Step 1: Get list of top N clones
    print(f"Reading top {args.number} clones from stats file...")
    ranked_clone_ids = get_top_clones(args.stats, args.number)

    if not ranked_clone_ids:
        print("No clones found or N is 0. Exiting.")
        sys.exit(0)

    # Step 2: Calculate clonotype counts
    print("Scanning sequence file for clonotype IDs (this may take a moment)...")
    counts = find_clonotype_counts(args.seqs, ranked_clone_ids)

    # Step 3: Write results
    write_output(args.output, ranked_clone_ids, counts)


if __name__ == "__main__":
    main()
