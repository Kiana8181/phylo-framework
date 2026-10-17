import pandas as pd


def collapse_duplicates(df: pd.DataFrame, dup_ref_cols=["v_call", "j_call", "cdr3_aa"]):
    """
    Identifies duplicates based on v_call, j_call, and cdr3_aa.
    Collapse and only keep the first occurrence. (filtered DataFrame)
    Returns a dictionary of ID relationships and a filtered DataFrame.
    """

    collapse_df = df.drop_duplicates(subset=dup_ref_cols, keep="first").copy()

    # gather sequence_id of all rows with same dup_ref_cols
    grouped_ids = df.groupby(dup_ref_cols)["sequence_id"].apply(list)

    # e.g: {'S1': ['S4', 'S6', 'S9', 'S10']}
    seq_id_first_to_rest_map = {ids[0]: ids[1:] for ids in grouped_ids}

    return seq_id_first_to_rest_map, collapse_df
