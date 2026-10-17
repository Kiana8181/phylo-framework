# ---------
# Global configs
REMOVE_INTERMEDIATE_FILES = True

# ---------
# Initial clustering step parameters
INITIAL_CLUSTERING_THRESHOLD = 0.7
ABUNDANCE_THRESHOLD = 3

# ---------
# The refinemet step parameters
# 1:Binary, 2:Levenshtein, 3:GIANA, 4:K-mers
V_DISTANCE = 1

# 1:Binary, 2:Levenshtein, 3:GIANA, 4:K-mers
J_DISTANCE = 2

# 1:Binary, 2:Levenshtein, 3:GIANA, 4:K-mers
CDR3_DISTANCE = 2

# 1:Mean, 2:Weighted Mean, 3:Harmonic Mean
COMBINE_DISTANCE = 1

# 0:No, 1:Yes
MERGE_SINGLETON = 1

# ---------
# Two level clonal info parameters

# L1: Full VDJ nucleotide identical (Strict)
# L2: V/D/J allele + anchors + exact CDR3 AA (IMGT)
# L3: exact CDR3 AA match (B-DIVE)
# L4: V gene + CDR3 AA similarity ≥ threshold (Similarity)
# L5: Same V gene + same CDR3 AA length + similarity ≥ threshold (Length-controlled Similarity)
CLONOTYPE_METHOD = "L3"

# Required for L4 and L5
SIMILARITY_THRESHOLD = 0.8

# Selecting clone parameters
NUMBER_TOP_CLONE = 5
