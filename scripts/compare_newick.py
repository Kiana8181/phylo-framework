#!/usr/bin/env python3
"""Cross-run reproducibility comparator for Phylo-Framework method outputs.

Compares three independent runs of the same method and reports:
  - bytewise identity of newick.nwk
  - canonical-form equivalence after child sorting and inferred-name stripping
  - clade-set equality
  - root label identity

Usage: compare_newick.py output/<method>
"""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path
from Bio import Phylo   # biopython
from io import StringIO

INFERRED = re.compile(r"^(Inferred\d+|S\d{6}(:S\d{6})?)$")

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p: Path):
    return Phylo.read(StringIO(p.read_text()), "newick")

def strip_inferred(tree):
    for cl in tree.find_clades():
        if cl.name and INFERRED.match(cl.name):
            cl.name = None
    return tree

def leaf_key(clade):
    leaves = [l.name for l in clade.get_terminals() if l.name]
    return min(leaves) if leaves else ""

def canon_sort(tree):
    for cl in tree.find_clades():
        if cl.clades:
            cl.clades.sort(key=leaf_key)
    return tree

def to_newick(tree) -> str:
    buf = StringIO()
    Phylo.write(tree, buf, "newick")
    return buf.getvalue().strip()

def clades(tree) -> set[frozenset[str]]:
    return {frozenset(l.name for l in cl.get_terminals() if l.name)
            for cl in tree.find_clades() if cl.clades}

def root_label(tree) -> str:
    # heuristic: the outermost non-inferred label
    t = list(tree.find_clades())
    return next((c.name for c in t if c.name and not INFERRED.match(c.name)), "")

def main(method_dir: str):
    runs = sorted(Path(method_dir).glob("Run */newick.nwk"))
    assert len(runs) == 3, f"expected 3 runs, found {len(runs)}"
    hashes = [sha256(p) for p in runs]
    trees  = [canon_sort(strip_inferred(load(p))) for p in runs]
    newicks = [to_newick(t) for t in trees]
    csets   = [clades(t) for t in trees]
    roots   = [root_label(load(p)) for p in runs]
    result = {
        "runs": [str(p) for p in runs],
        "sha256": hashes,
        "bitwise_identical": len(set(hashes)) == 1,
        "canonical_equal":   len(set(newicks)) == 1,
        "clade_sets_equal":  all(c == csets[0] for c in csets),
        "root_labels":       roots,
        "root_label_equal":  len(set(roots)) == 1,
    }
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main(sys.argv[1])
