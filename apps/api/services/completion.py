"""What a method's result must contain before its run may be reported as DONE.

Verifying the files a method *declares* is not enough: a method that reports
success but declares nothing (or leaves out its main output) would pass that
check with an empty list. So each method also has positive success criteria,
kept with its other contracts in
``packages/contracts/methods/<method>/completion.json``:

    minTrees               fewest trees a successful run delivers
    requiredArtifactRoles  artifact roles that must be present (for all four
                           methods: the result bundle, ``clone_bundle_zip``)

A result that misses one of these is not a finished analysis and the run ends
as ERROR [INCOMPLETE_RESULT], whatever status the method service reported.

Deliberately NOT required, because methods legitimately succeed without them:
  - rendered tree images (a method may fail to draw a tree it built; it says so
    in its warnings and the tree is still shown from its Newick);
  - method-specific extras (GCtree abundance charts, BrepPhylo PDFs, ...);
  - the execution log: a run whose scientific output is complete and stored is
    kept, and carries a warning that its log could not be saved.

A method without a completion.json gets the default rule: at least one tree
and at least one stored file besides the log.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from apps.api.contracts.loader import METHODS_DIR, _read_json
from apps.api.database.models import ArtifactKind

CODE_INCOMPLETE_RESULT = "INCOMPLETE_RESULT"
LOG_MISSING_WARNING = {
    "code": "EXECUTION_LOG_MISSING",
    "message": "The run completed, but its execution log could not be saved.",
}

_ROLE_NAMES = {
    "clone_bundle_zip": "the result bundle (the downloadable archive of its output files)",
    "phylogeny": "the rendered tree image",
}


@dataclass(frozen=True)
class CompletionRule:
    min_trees: int = 1
    required_roles: tuple[str, ...] = ()
    # Used when a method declares no required role: some output file must exist.
    require_any_output: bool = True


def completion_rule(method_id: str) -> CompletionRule:
    path = METHODS_DIR / method_id / "completion.json"
    if not path.exists():
        return CompletionRule()
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    min_trees = data.get("minTrees", 1)
    roles = data.get("requiredArtifactRoles", [])
    if not isinstance(min_trees, int) or isinstance(min_trees, bool) or min_trees < 0:
        raise ValueError(f"{path}: minTrees must be a non-negative integer")
    if not isinstance(roles, list) or not all(isinstance(r, str) and r.strip() for r in roles):
        raise ValueError(f"{path}: requiredArtifactRoles must be a list of role names")
    return CompletionRule(
        min_trees=min_trees,
        required_roles=tuple(r.strip() for r in roles),
        require_any_output=not roles,
    )


def _is_log(row: dict[str, Any]) -> bool:
    return row.get("artifact_kind") == ArtifactKind.LOG or row.get("artifact_role") == "log"


def missing_requirements(
    method_id: str,
    raw_result: dict[str, Any],
    tree_rows: list[dict[str, Any]],
    artifact_rows: list[dict[str, Any]],
    rule: Optional[CompletionRule] = None,
) -> list[str]:
    """Reasons this result is not a finished analysis (empty when it is)."""
    rule = rule or completion_rule(method_id)
    problems: list[str] = []
    if raw_result.get("ok") is False:
        problems.append("the method reported that it did not succeed")
    usable_trees = [t for t in tree_rows if str(t.get("newick") or "").strip()]
    if len(usable_trees) < rule.min_trees:
        problems.append(
            "it produced no tree" if rule.min_trees == 1
            else f"it produced {len(usable_trees)} tree(s) where at least {rule.min_trees} are expected"
        )
    roles = {str(row.get("artifact_role") or "") for row in artifact_rows}
    for role in rule.required_roles:
        if role not in roles:
            problems.append(f"{_ROLE_NAMES.get(role, f'the {role} file')} is missing")
    if rule.require_any_output and not any(not _is_log(row) for row in artifact_rows):
        problems.append("it delivered no output file")
    return problems


def has_execution_log(artifact_rows: list[dict[str, Any]]) -> bool:
    return any(_is_log(row) for row in artifact_rows)
