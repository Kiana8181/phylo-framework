import sys

import pandas as pd


def read_tsv(file_path, **kwargs):
    try:
        df = pd.read_csv(
            file_path,
            sep="\t",
            on_bad_lines="skip",
            low_memory=False,
            dtype=str,
            **kwargs,
        )
        return df
    except Exception as e:
        print(f"Error: {e} - util - read_tsv - file_path: {file_path}")
        sys.exit(1)


def write_tsv(df, file_path):
    try:
        df.to_csv(file_path, sep="\t", index=False)
    except Exception as e:
        print(f"Error: {e} - util - write_tsv - file_path: {file_path}")
        sys.exit(1)
