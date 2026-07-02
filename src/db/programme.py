"""
Human-readable programme labels + call-year extraction.
=======================================================

The raw CORDIS export encodes the funding programme only as a machine code
(``programme_code`` such as ``HORIZON.1.2`` or ``H2020-EU.1.1.``) plus a very
verbose ``programme_title``. For reporting we want a **concise, human-readable
programme label** (e.g. "ERC StG", "MSCA DN", "Health"), and we want a **call
year for every project**, not only ERC ones.

Two derived fields are produced from the existing ``programme_code``,
``call_identifier`` and ``topic_title`` columns:

* ``programme_label`` — a short funding-family name. For the two most important
  families this is broken down into sub-schemes:
    - ERC  → ``ERC StG`` / ``ERC CoG`` / ``ERC AdG`` / ``ERC SyG`` / ``ERC PoC``
             (from the grant-type suffix of the call identifier).
    - MSCA → ``MSCA DN`` (Doctoral Networks; ``ITN`` in Horizon 2020) /
             ``MSCA PF`` (Postdoctoral Fellowships; ``IF`` in Horizon 2020),
             other MSCA actions (RISE/SE/COFUND) stay as ``MSCA``.
* ``call_year`` — the first 4-digit year found in ``call_identifier``
  (e.g. ``ERC-2025-COG`` → 2025, ``HORIZON-MSCA-2025-DN-01`` → 2025), falling
  back to the project start year.

All mappings live here so they are easy to review and extend.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# programme_code prefix  ->  concise human-readable label (family level)
# ---------------------------------------------------------------------------
# Matching is done by LONGEST prefix, so more specific codes win over the
# generic pillar (e.g. "HORIZON.2.4" beats a hypothetical "HORIZON.2").
# ERC and MSCA are refined further below into sub-schemes.
PROGRAMME_MAP: dict[str, str] = {
    # ── Horizon Europe (2021–2027) ─────────────────────────────────────────
    "HORIZON.1.1": "ERC",
    "HORIZON.1.2": "MSCA",
    "HORIZON.1.3": "Research Infrastructures",
    "HORIZON.2.1": "Health",
    "HORIZON.2.2": "Culture, Creativity & Inclusive Society",
    "HORIZON.2.3": "Civil Security for Society",
    "HORIZON.2.4": "Digital, Industry & Space",
    "HORIZON.2.5": "Climate, Energy & Mobility",
    "HORIZON.2.6": "Food, Bioeconomy & Environment",
    "HORIZON.3.1": "European Innovation Council (EIC)",
    "HORIZON.3.2": "European Innovation Ecosystems",
    "HORIZON.4.1": "Widening Participation",
    "HORIZON.4.2": "Reforming the R&I System",
    # ── Horizon 2020 (2014–2020) ───────────────────────────────────────────
    "H2020-EU.1.1": "ERC",
    "H2020-EU.1.2": "Future & Emerging Technologies (FET)",
    "H2020-EU.1.3": "MSCA",
    "H2020-EU.1.4": "Research Infrastructures",
    "H2020-EU.2.1": "Industrial Leadership (LEIT)",
    "H2020-EU.2.2": "Access to Risk Finance",
    "H2020-EU.2.3": "Innovation in SMEs",
    "H2020-EU.3.1": "Health",
    "H2020-EU.3.2": "Food Security & Bioeconomy",
    "H2020-EU.3.3": "Secure, Clean & Efficient Energy",
    "H2020-EU.3.4": "Smart, Green & Integrated Transport",
    "H2020-EU.3.5": "Climate Action & Environment",
    "H2020-EU.3.6": "Inclusive & Reflective Societies",
    "H2020-EU.3.7": "Secure Societies",
    "H2020-EU.3": "Societal Challenges",
    "H2020-EU.5": "Science with & for Society",
    "H2020-Euratom": "Euratom",
    # ── FP7 (2007–2013) ────────────────────────────────────────────────────
    "FP7-IDEAS-ERC": "ERC",
    "FP7-PEOPLE": "MSCA",   # FP7 Marie Curie actions
    "FP7-HEALTH": "Health",
    "FP7-ICT": "ICT",
    "FP7-SSH": "Socio-economic Sciences & Humanities",
    "FP7-SME": "Research for SMEs",
    "FP7-JTI": "Joint Technology Initiatives",
}

# Fallback keyword rules applied to the call_identifier when the programme_code
# is missing or unmapped. Evaluated in order; first match wins.
_CALL_KEYWORD_RULES: list[tuple[str, str]] = [
    ("ERC", "ERC"),
    ("MSCA", "MSCA"),
    ("EIC", "European Innovation Council (EIC)"),
    ("FET", "Future & Emerging Technologies (FET)"),
    ("INFRA", "Research Infrastructures"),
    ("PHC", "Health"),
    ("SC1", "Health"),
    ("ICT", "ICT"),
]

# ── ERC grant-type suffixes → display sub-label ───────────────────────────
# Matched as a whole token in the (upper-cased) call identifier.
ERC_GRANT_TYPES: dict[str, str] = {
    "STG": "StG",   # Starting Grant
    "COG": "CoG",   # Consolidator Grant
    "ADG": "AdG",   # Advanced Grant
    "SYG": "SyG",   # Synergy Grant
    "POC": "PoC",   # Proof of Concept
}

# ── MSCA action tokens → DN / PF sub-label ────────────────────────────────
# Horizon Europe uses DN / PF; Horizon 2020 used ITN / IF (+ FP7 IEF/IIF/IOF).
MSCA_DN_TOKENS = {"DN", "ITN"}                       # Doctoral Networks
MSCA_PF_TOKENS = {"PF", "IF", "IEF", "IIF", "IOF", "GF"}  # Postdoc Fellowships

# Precompute prefixes sorted by length (longest first) for greedy matching.
_PROGRAMME_PREFIXES = sorted(PROGRAMME_MAP, key=len, reverse=True)

# A 4-digit year between 2000 and 2099 (covers all EU FP7/H2020/Horizon calls).
_YEAR_RE = re.compile(r"(20\d{2})")


def _tokens(call_identifier: str | None) -> set[str]:
    """Upper-case the call id and split into alphanumeric tokens."""
    if not call_identifier:
        return set()
    return {t for t in re.split(r"[^A-Za-z0-9]+", call_identifier.upper()) if t}


def _erc_sublabel(call_identifier: str | None) -> str:
    """Return 'ERC StG' / 'ERC CoG' / … or plain 'ERC' when unknown."""
    for tok in _tokens(call_identifier):
        if tok in ERC_GRANT_TYPES:
            return f"ERC {ERC_GRANT_TYPES[tok]}"
    return "ERC"


def _msca_sublabel(call_identifier: str | None) -> str:
    """Return 'MSCA DN' / 'MSCA PF' or plain 'MSCA' for other actions."""
    toks = _tokens(call_identifier)
    if toks & MSCA_DN_TOKENS:
        return "MSCA DN"
    if toks & MSCA_PF_TOKENS:
        return "MSCA PF"
    return "MSCA"


def _family_label(programme_code: str | None, call_identifier: str | None) -> str | None:
    """Resolve the coarse funding family (ERC / MSCA / Health / …)."""
    code = (programme_code or "").strip()
    if code:
        norm = code.rstrip(".")
        for prefix in _PROGRAMME_PREFIXES:
            if norm.startswith(prefix):
                return PROGRAMME_MAP[prefix]

    call = (call_identifier or "").upper()
    if call:
        for token, label in _CALL_KEYWORD_RULES:
            if token in call:
                return label

    if code:
        root = code.split("-")[0].split(".")[0]
        return root or None
    return None


def derive_programme_label(
    programme_code: str | None,
    call_identifier: str | None = None,
    programme_title: str | None = None,
) -> str | None:
    """
    Return a concise human-readable programme label, with ERC/MSCA sub-schemes.

    Resolution:
      1. Coarse family from :data:`PROGRAMME_MAP` (longest ``programme_code``
         prefix), or a call-identifier keyword fallback.
      2. If the family is ERC, refine to ``ERC <GrantType>`` from the call.
      3. If the family is MSCA, refine to ``MSCA DN`` / ``MSCA PF`` from the
         call (ITN→DN, IF→PF for Horizon 2020 / FP7).
    """
    family = _family_label(programme_code, call_identifier)
    if family == "ERC":
        return _erc_sublabel(call_identifier)
    if family == "MSCA":
        return _msca_sublabel(call_identifier)
    return family


def derive_call_year(
    call_identifier: str | None,
    start_date: str | None = None,
) -> int | None:
    """
    Extract the call year (first 4-digit ``20xx`` in the call identifier).

    Works for every framework:
      * ``ERC-2025-COG``            -> 2025
      * ``H2020-MSCA-ITN-2014``     -> 2014
      * ``H2020-PHC-2014-2015``     -> 2014 (first/opening year)
      * ``HORIZON-MSCA-2025-DN-01`` -> 2025

    Falls back to the year of ``start_date`` (ISO ``YYYY-...``) when the call
    identifier is missing or contains no year.
    """
    if call_identifier:
        m = _YEAR_RE.search(str(call_identifier))
        if m:
            return int(m.group(1))

    if start_date:
        try:
            return int(str(start_date)[:4])
        except (ValueError, TypeError):
            return None
    return None
