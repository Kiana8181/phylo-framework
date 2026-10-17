import sys
import argparse
import numpy as np
import heapq
from scipy.spatial.distance import pdist, squareform
from Bio import SeqIO
from ete3 import Tree

# =============================================================================
# Data Handling and Distance Calculation
# =============================================================================


def read_fasta_abundance(fasta_file):
    """
    Parses FASTA file. Expects headers like 'ID@Abundance' or just 'ID'.
    Returns sequences, labels, abundance dict, and the index of the root ('germline').
    """
    labels = []
    sequences = []
    abundance = {}
    root_idx = 0

    # Biopython parsing
    records = list(SeqIO.parse(fasta_file, "fasta"))

    for i, record in enumerate(records):
        header = record.id
        seq = str(record.seq)

        # Parse ID and Abundance
        if "@" in header:
            parts = header.split("@")
            seq_id = parts[0]
            try:
                abund = int(parts[1])
            except ValueError:
                abund = 1
        else:
            seq_id = header
            abund = 1

        # Store Data
        if seq_id not in abundance:
            labels.append(seq_id)
            sequences.append(seq)
            abundance[seq_id] = abund
        else:
            # Aggregate abundance if ID repeats
            abundance[seq_id] += abund

        # Identify Root
        if seq_id == "germline":
            root_idx = labels.index(seq_id)

    return labels, sequences, abundance, root_idx


def compute_hamming_matrix(sequences):
    """
    Efficiently computes the Hamming distance matrix using Scipy.
    Returns a square numpy array of integer distances.
    """
    if not sequences:
        return np.zeros((0, 0))

    # Convert sequences to a numpy character array
    # We assume aligned sequences (same length).
    try:
        # FIX: 'sequences' is already a list of strings, so we access the string 's' directly
        # and encode it. We do NOT use .seq here.
        seq_array = np.array([list(s.encode("utf-8")) for s in sequences])

        # Scipy pdist 'hamming' returns proportion of disagreement.
        # Multiply by length to get integer edits.
        dist_vector = pdist(seq_array, metric="hamming")
        dist_matrix_float = squareform(dist_vector)
        seq_len = len(sequences[0])

        # Round to handle float precision issues, convert to int
        dist_matrix = np.round(dist_matrix_float * seq_len).astype(int)

    except Exception as e:
        print(f"Error computing distance matrix (check sequence alignment): {e}")
        sys.exit(1)

    return dist_matrix

# =============================================================================
# Tree Construction (Prim's Algorithm with Abundance Tie-Breaking)
# =============================================================================


def prims_mst_abundance(adj_matrix, root_idx, labels, abundance, use_abundance=True):
    """
    Builds an MST using Prim's algorithm.
    Prioritizes Minimum Distance.
    Tie-breaker: Maximize (Abundance[Parent] + Abundance[Child]).
    """
    num_nodes = len(labels)
    visited = {root_idx}

    # Initialize Tree structure
    t = Tree()
    root_node = t.add_child(name=labels[root_idx])

    # Map label to tree node object for quick access
    nodes_in_tree = {labels[root_idx]: root_node}

    # Priority Queue stores: (Distance, -Total_Abundance, Parent_Idx, Child_Idx)
    # We use negative abundance because heapq is a Min-Heap.
    pq = []

    edge_info_list = []

    def add_edges_from_node(u_idx):
        for v_idx in range(num_nodes):
            if v_idx not in visited:
                dist = adj_matrix[u_idx][v_idx]

                if use_abundance:
                    # Higher abundance is better, so make it negative for Min-Heap
                    combined_abundance = (
                        abundance[labels[u_idx]] + abundance[labels[v_idx]]
                    )
                    priority_score = -combined_abundance
                else:
                    # If not using abundance, use index as deterministic tie breaker
                    priority_score = v_idx

                heapq.heappush(pq, (dist, priority_score, u_idx, v_idx))

    # Initial population of heap from root
    add_edges_from_node(root_idx)

    while len(visited) < num_nodes and pq:
        dist, _, u, v = heapq.heappop(pq)

        if v in visited:
            continue

        visited.add(v)

        # Add to ETE3 Tree
        parent_label = labels[u]
        child_label = labels[v]

        parent_node = nodes_in_tree[parent_label]
        new_node = parent_node.add_child(name=child_label, dist=dist)
        nodes_in_tree[child_label] = new_node

        # Record info
        edge_info_list.append(f"{parent_label}\t{child_label}\t{dist}")

        # Add new candidate edges
        add_edges_from_node(v)

    if len(visited) < num_nodes:
        print("Warning: Tree is disconnected. Not all nodes were reachable.")

    info_str = "\n".join(edge_info_list)
    return t, info_str


# =============================================================================
# Tree Revision / Editing
# =============================================================================


def refine_tree(input_tree, adj_matrix, labels):
    refined_tree = Tree()
    collapsed_nodes = set()

    def get_or_create_node(name):
        search = refined_tree.search_nodes(name=name)
        if search:
            return search[0]
        return None

    # Pre-order traversal
    for original_node in input_tree.traverse("preorder"):

        # 1. Handle Root
        if original_node.is_root():
            if original_node.name:
                refined_tree.add_child(name=original_node.name)
            else:
                for child in original_node.children:
                    refined_tree.add_child(name=child.name)
            continue

        # --- FIX STARTS HERE ---
        # REMOVED: if original_node.name in collapsed_nodes: continue

        # 2. Find this node in the new tree.
        # Even if it was "collapsed" earlier (moved under a dummy), it exists in refined_tree.
        current_new_node = get_or_create_node(original_node.name)

        # If the node wasn't added yet (shouldn't happen if preorder is respected), skip
        if not current_new_node:
            continue
        # --- FIX ENDS HERE ---

        # 3. Analyze Children
        children = original_node.get_children()

        # We need the index of the current node
        parent_name = original_node.name
        try:
            p_idx = labels.index(parent_name)
        except ValueError:
            continue

        for n in children:
            # Skip if this child was already processed (e.g., as a sibling in a previous collapse)
            # Note: In the legacy code, 'ardColapsed' prevents re-adding nodes as children.
            if n.name in collapsed_nodes:
                continue

            n_idx = labels.index(n.name)
            dist_n_p = adj_matrix[n_idx][p_idx]

            siblings_to_collapse = []

            for i in children:
                if i.name == n.name or i.name in collapsed_nodes:
                    continue

                i_idx = labels.index(i.name)
                dist_n_i = adj_matrix[n_idx][i_idx]
                dist_i_p = adj_matrix[i_idx][p_idx]

                if (dist_n_i <= dist_n_p) and (dist_n_i <= dist_i_p):
                    siblings_to_collapse.append(i.name)

            if siblings_to_collapse:
                dummy = current_new_node.add_child(name=None)
                dummy.add_child(name=n.name)
                collapsed_nodes.add(n.name)

                for sib_name in siblings_to_collapse:
                    dummy.add_child(name=sib_name)
                    collapsed_nodes.add(sib_name)
            else:
                if n.name not in collapsed_nodes:
                    current_new_node.add_child(name=n.name)
                    # Do NOT add to collapsed_nodes here, so it can be visited as a parent later

    return refined_tree


def check_consistency(tree, labels):
    """
    Verifies that every label in the input exists exactly once in the tree.
    """
    tree_labels = []
    for node in tree.traverse("preorder"):
        if node.name and node.name in labels:
            tree_labels.append(node.name)
        elif node.name and node.name != "NoName":
            # "NoName" or None is often used for internal nodes
            pass

    unique_tree = set(tree_labels)
    if len(unique_tree) != len(labels):
        print(
            f"Consistency Check Failed: Input Labels {len(labels)}, Tree Labels {len(unique_tree)}"
        )
        return False
    return True


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="ClonalTree: Construct MST from FASTA sequences."
    )
    parser.add_argument(
        "-i", "--fastaFile", required=True, help="Input sequences in FASTA format"
    )
    parser.add_argument("-o", "--outputFile", required=True, help="Output file prefix")
    parser.add_argument(
        "-a",
        "--useAbundance",
        default="0",
        help="Use abundance? '0' for True, '1' for False",
    )
    parser.add_argument(
        "-r",
        "--revision",
        default="0",
        help="Perform tree revision? '0' for True, '1' for False",
    )

    args = parser.parse_args()

    # Logic from original makeBoolean: '0' -> True, else False
    use_abundance = args.useAbundance == "0"
    do_revision = args.revision == "0"

    print(f"Reading FASTA: {args.fastaFile}")
    labels, sequences, abundance, root_idx = read_fasta_abundance(args.fastaFile)

    if not labels:
        print("No sequences found.")
        sys.exit(1)

    print(f"Computing Distance Matrix for {len(labels)} sequences...")
    adj_matrix = compute_hamming_matrix(sequences)

    print("Building MST (Prim's Algorithm)...")
    tree, info_log = prims_mst_abundance(
        adj_matrix, root_idx, labels, abundance, use_abundance
    )

    if do_revision:
        print("Performing Tree Revision...")
        tree = refine_tree(tree, adj_matrix, labels)

    print("Checking Consistency...")
    if check_consistency(tree, labels):
        # Write output
        # Format 1 is Newick with internal node names
        tree.write(format=1, outfile=args.outputFile)

        # Write edge info CSV
        csv_file = args.outputFile + ".csv"
        with open(csv_file, "w") as f:
            f.write(info_log)

        print(f"Done. Tree saved to {args.outputFile} and {csv_file}")
    else:
        print("Error: Tree inconsistency detected. Output aborted.")


if __name__ == "__main__":
    main()
