"""
CONFIGURATION FILE FOR B-DIVE PIPELINE
==========================================================

This file contains all key definitions and parameters that can be easily modified
for different clone/clonotype definitions and root/naive sequence selection methods.

IMPORTANT: When modifying definitions, update both the parameters here and the
corresponding logic in the relevant scripts.
"""

# ============================================================================
# CLONE DEFINITION PARAMETERS
# ============================================================================

# GTM (Grouping Tool Method) Clone Definition
# --------------------------------------------
# Clones are defined as sequences that share:
#   1. Same V gene (without allele consideration)
#   2. Same J gene (without allele consideration)  
#   3. CDR3 similarity above CLONE_THRESHOLD

CLONE_DEFINITION_GTM = {
    'v_gene_include_allele': False,  # If True, considers V gene allele; if False, only V gene family
    'j_gene_include_allele': False,  # If True, considers J gene allele; if False, only J gene family
    'cdr3_similarity_threshold': 0.7,  # CDR3 similarity threshold (0-1) for grouping into same clone
    'cdr3_distance_method': 'hamming',  # Options: 'hamming', 'levenshtein', 'alignment'
    'use_refinement': True,  # Whether to use silhouette-based refinement step
}

# ============================================================================
# CLONOTYPE DEFINITION PARAMETERS
# ============================================================================

# Clonotype Definition
# ---------------------
# Clonotypes are defined within clones as sequences with:
#   - Identical CDR3 amino acid sequence (exact match)
#   - Same V-(D)-J rearrangement
#   - Conserved anchors (C104, W or F 118)

CLONOTYPE_DEFINITION = {
    'cdr3_match_exact': True,  # If True, requires exact CDR3 AA match; if False, allows similarity
    'cdr3_similarity_threshold': 1.0,  # Only used if cdr3_match_exact = False
    'require_same_vj': True,  # Whether to require same V and J genes
    'check_anchors': False,  # Whether to check for conserved anchors (C104, W/F118)
}

# ============================================================================
# ROOT/NAIVE/GERMLINE SEQUENCE DEFINITION
# ============================================================================

# Root/Naive/Germline Selection Method
# -------------------------------------
# The root sequence is used as the starting point for lineage tree construction.
# Current default: Most abundant clonotype within a clone

ROOT_SELECTION_METHOD = {
    'method': 'most_abundant_clonotype',  # Options: 
                                          #   - 'most_abundant_clonotype' (current default)
                                          #   - 'highest_v_identity'
                                          #   - 'lowest_mutation_count'
                                          #   - 'first_sequence'
                                          #   - 'closest_to_germline'
    
    'most_abundant_clonotype': {
        'tie_breaker': 'highest_v_identity',  # If abundance is equal, use this
    },
    
    'highest_v_identity': {
        'min_v_identity': 0.95,  # Minimum V gene identity to consider
        'tie_breaker': 'most_abundant',
    },
    
    'closest_to_germline': {
        'germline_source': 'imgt',  # Options: 'imgt', 'inferred', 'provided'
        'distance_metric': 'hamming',  # Options: 'hamming', 'levenshtein', 'edit'
    },
}

# ============================================================================
# TREE CONSTRUCTION PARAMETERS
# ============================================================================

TREE_CONSTRUCTION = {
    'use_abundance': True,  # Whether to consider sequence abundance in tree building
    'revision': True,  # Whether to perform tree revision/optimization
    'distance_metric': 'hamming',  # Distance metric for tree construction
    'tree_algorithm': 'mst',  # Options: 'mst' (minimum spanning tree), 'nj' (neighbor joining)
}

# ============================================================================
# HELPER FUNCTIONS FOR ACCESSING CONFIG
# ============================================================================

def get_clone_threshold(method='GTM'):
    """Get the CDR3 similarity threshold for clone definition."""
    if method.upper() == 'GTM':
        return CLONE_DEFINITION_GTM['cdr3_similarity_threshold']
    else:
        raise ValueError(f"Unknown method: {method}")

def get_root_selection_method():
    """Get the current root/naive selection method."""
    return ROOT_SELECTION_METHOD['method']

def get_clonotype_definition():
    """Get clonotype definition parameters."""
    return CLONOTYPE_DEFINITION.copy()

# ============================================================================
# LOCATIONS OF KEY DEFINITIONS IN CODE
# ============================================================================

KEY_DEFINITION_LOCATIONS = {
    'clone_definition_gtm': {
        'file': 'code/clustering/initial_clustering.py',
        'function': 'group_clone_VJ_cdr3',
        'line_range': '90-129',
        'description': 'Groups sequences into clones based on V, J, and CDR3 similarity'
    },
    'clonotype_definition': {
        'file': 'code/clustering/two_level_clonal_info.py',
        'function': 'gather_clone_clonotype_info',
        'line_range': '58-81',
        'description': 'Defines clonotypes within clones based on identical CDR3 AA sequence'
    },
    'root_selection': {
        'file': 'code/alignment/alignment_intraconal.py',
        'function': 'read_seq_info',
        'line_range': '36-46',
        'description': 'Selects root/naive sequence (currently: most abundant clonotype)'
    },
    'tree_construction': {
        'file': 'code/tree/clonalTree.py',
        'function': 'main',
        'line_range': '55-94',
        'description': 'Constructs lineage trees using MST algorithm'
    }
}
