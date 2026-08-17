"""Detect gctree's ``name@abundance`` FASTA header convention.

GCtree writes IDs like ``seq3@9`` in its own output, but ``deduplicate`` cannot
read that form back — its ``--id_abundances`` flag only recognises IDs that are
entirely digits — so the abundances are silently lost. The ``@`` additionally
survives into the PHYLIP file, where DNAPARS rewrites the taxon name and gctree's
later root lookup fails. The GCtree wrapper therefore asks the user what the
number means, and this module tells the form when to show that question.

NOTE: the regex literal is intentionally duplicated in
``services/gctree/app.py`` (FASTA_ID_AT_ABUNDANCE_RE) and
``apps/web/lib/fastaIdStyle.ts`` — three deploy units with no shared runtime.
Keep all three in sync.
"""

from __future__ import annotations

import re
from typing import Iterable

AT_ABUNDANCE_RE = re.compile(r"^(?P<name>[^@\s]+)@(?P<abundance>\d+)$")

STYLE_AT_ABUNDANCE = "at_abundance"
STYLE_OTHER_AT = "other_at"
STYLE_PLAIN = "plain"


def classify_fasta_headers(headers: Iterable[str]) -> str:
    """Classify FASTA IDs as ``at_abundance``, ``other_at`` or ``plain``.

    ``at_abundance`` means *every* ID matches ``name@N``; ``other_at`` means at
    least one contains ``@`` but they do not all match, so it cannot be read as
    an abundance encoding.
    """
    has_at = False
    all_at_abundance = True
    saw_any = False

    for header in headers:
        sid = header.strip().split()[0] if header.strip() else ""
        if not sid:
            continue
        saw_any = True
        if "@" in sid:
            has_at = True
        if not AT_ABUNDANCE_RE.fullmatch(sid):
            all_at_abundance = False

    if not saw_any or not has_at:
        return STYLE_PLAIN
    return STYLE_AT_ABUNDANCE if all_at_abundance else STYLE_OTHER_AT


def extract_fasta_headers(text: str, *, truncated: bool = False) -> list[str]:
    """Collect the ID token of every ``>`` line in a (possibly partial) FASTA.

    When ``truncated`` the final line is discarded: it may be a header cut in
    half, which would otherwise be misclassified.
    """
    lines = text.splitlines()
    if truncated and lines:
        lines = lines[:-1]
    return [line[1:].strip() for line in lines if line.startswith(">")]
