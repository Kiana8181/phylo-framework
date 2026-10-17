import argparse
import sys
from pathlib import Path


def rename_files_recursively(root_dir: Path) -> None:
    """
    Recursively scans the directory and removes specific substring from filenames.
    """
    target_substring = "_alignment_added_preprocess"

    # rglob('*') recursively finds all files and directories
    for path in root_dir.rglob("*"):
        if path.is_file() and target_substring in path.name:

            # Create the new name by replacing the target string
            new_name = path.name.replace(target_substring, "")

            # with_name creates a new Path object with the filename changed
            new_path = path.with_name(new_name)

            try:
                # Rename the file
                path.rename(new_path)
                print(f"Renamed: '{path.name}' -> '{new_path.name}'")
            except OSError as e:
                print(f"Error renaming '{path.name}': {e}", file=sys.stderr)


if __name__ == "__main__":
    # Initialize argument parser
    parser = argparse.ArgumentParser(
        description="Recursively remove '_alignment_added_preprocess' from filenames."
    )

    # Add the directory argument (type=Path automatically converts input to a Path object)
    parser.add_argument("directory", type=Path, help="The target directory path")

    # Parse arguments
    args = parser.parse_args()

    # Validate directory
    if not args.directory.exists() or not args.directory.is_dir():
        print(
            f"Error: The path '{args.directory}' does not exist or is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    rename_files_recursively(args.directory)
