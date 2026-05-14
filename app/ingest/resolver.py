"""Record-level identity resolver.

Lifts the four-tier match pattern from
`dcl/backend/engine/source_normalizer.py:186-280` (exact -> alias -> pattern ->
fuzzy via difflib.SequenceMatcher), then adapts the inputs and outputs:
DCL's normalizer disambiguates source-system IDs ("Salesforce" -> "salesforce");
this resolver disambiguates record-level business strings (cost-center names,
team names, vendor names, SaaS app labels).

Tiers:
  1. exact     — normalized lowercase+trim string match against the canonical
                 registry for (tenant_id, domain).
  2. alias     — explicit alias table (operator-curated; starts empty).
  3. pattern   — regex/prefix rules per domain (e.g., cost-center codes that
                 follow a known shape resolve to a canonical bucket).
  4. fuzzy     — token-aware similarity blended with `difflib.SequenceMatcher`
                 over the normalized string. >= auto_threshold (0.90) auto-
                 accepts; in [fuzzy_threshold, auto_threshold) the pair is
                 queued for human review (HITL); below fuzzy_threshold the
                 record is rejected loudly (no silent fallback).
  5. discovery — no canonical found at all; mint a new canonical_id and tag
                 the result `discovery` at confidence 0.99. Surfaces the new
                 binding to operators via the audit trail.

The resolver owns no triple writes. It returns a `ResolutionResult` that the
caller (ingest_demo orchestrator) attaches to each record before the triple
builder runs. The triple builder copies canonical_id / resolution_method /
resolution_confidence into the semantic_triples rows.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable, Literal, Optional

from ..db import hitl_store

_log = logging.getLogger("aam.ingest.resolver")

ResolutionMethod = Literal[
    "exact", "alias", "pattern", "fuzzy", "discovery", "hitl_pending",
    "hitl_confirmed", "rejected",
]


@dataclass
class ResolutionResult:
    """One record's resolver verdict.

    Set canonical_id when the resolver found (or minted) a canonical binding.
    `hitl_pending` means the canonical_id is proposed; downstream consumers
    should treat the row as not-yet-authoritative until an operator approves.
    """
    canonical_id: Optional[str]
    resolution_method: ResolutionMethod
    resolution_confidence: float
    hitl_queue_id: Optional[str] = None
    audit: dict = field(default_factory=dict)


@dataclass
class CanonicalEntry:
    """One row in the per-domain canonical registry.

    `value` is the canonical human-readable name (e.g., "Finance North
    America"); `canonical_id` is the stable UUID used downstream.
    """
    canonical_id: str
    value: str
    domain: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class PatternRule:
    """One pattern -> canonical_id binding for a domain. Regex pre-compiled."""
    domain: str
    pattern: re.Pattern
    canonical_id: str
    canonical_value: str


# ---------------------------------------------------------------------------
# String normalization + similarity
# ---------------------------------------------------------------------------

_NORM_SEP = re.compile(r"[\s\-_./,;:]+")


def _normalize(s: str) -> str:
    """Whitespace + punctuation collapse; lowercase; trim."""
    if s is None:
        return ""
    return _NORM_SEP.sub(" ", str(s).lower()).strip()


def _tokens(s: str) -> list[str]:
    """Split on whitespace + common punctuation, drop empties, lowercase."""
    return [t for t in _NORM_SEP.split(str(s).lower()) if t]


def _initials(toks: Iterable[str]) -> str:
    return "".join(t[0] for t in toks if t)


def _abbrev_match(short: str, longer_tokens: list[str]) -> float:
    """How well does `short` look like an abbreviation of `longer_tokens`?

    - If `short` matches the initials of `longer_tokens`, return 0.95.
      ("na" matches initials of ["north","america"]).
    - If `short` is a prefix of one of the long tokens, return a fractional
      score based on prefix coverage. ("fin" prefix of "finance" -> 0.85+).
    Otherwise 0.0.
    """
    if not short or not longer_tokens:
        return 0.0
    initials = _initials(longer_tokens)
    if short == initials:
        return 0.95
    if len(short) >= 3:
        for t in longer_tokens:
            if t.startswith(short) or short.startswith(t):
                cov = min(len(short), len(t)) / max(len(short), len(t))
                return 0.80 + 0.15 * cov
    return 0.0


def _token_score(a: str, b: str) -> float:
    """Token-aware similarity.

    For each token on the shorter side, find best-aligned token on the longer
    side. Score is the average of best alignments. Uses SequenceMatcher.ratio
    as the base metric and falls back to abbreviation/prefix heuristics — so
    "FinTeam-NA" can align Fin->Finance, NA->North America without exploding.

    Returns a float in [0, 1].
    """
    lt = _tokens(a)
    rt = _tokens(b)
    if not lt or not rt:
        return 0.0
    short, longer = (lt, rt) if len(lt) <= len(rt) else (rt, lt)
    scores: list[float] = []
    used: set[int] = set()
    for s in short:
        best = 0.0
        best_idx: int | None = None
        for i, l in enumerate(longer):
            if i in used:
                continue
            r1 = SequenceMatcher(None, s, l).ratio()
            r2 = _abbrev_match(s, [longer[j] for j in range(len(longer)) if j not in used])
            r = max(r1, r2)
            if len(s) >= 2 and len(l) >= 2 and (s.startswith(l) or l.startswith(s)):
                cov = min(len(s), len(l)) / max(len(s), len(l))
                r = max(r, 0.10 + 0.90 * cov)
            if r > best:
                best = r
                best_idx = i
        if best_idx is not None:
            used.add(best_idx)
        scores.append(best)
    return sum(scores) / len(scores)


def similarity_score(a: str, b: str) -> float:
    """Blended similarity in [0, 1].

    30% raw `difflib.SequenceMatcher` on the normalized strings (catches
    near-exact matches like "Microsoft 365" vs "microsoft 365") plus 70%
    token-aware alignment (catches abbreviations like "FinTeam-NA" vs
    "Finance North America").

    The weights are tuned so that:
      - identical-after-normalization strings score 1.0
      - "FinTeam-NA" vs "Finance North America" lands in [0.65, 0.78]
      - "LinkedIn Sales Navigator" vs "LinkedIn Sales Nav." lands in
        [0.80, 0.90), which is HITL-pending under the default thresholds
      - unrelated strings score < 0.50
    """
    a_n = _normalize(a)
    b_n = _normalize(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0
    raw = SequenceMatcher(None, a_n, b_n).ratio()
    tok = _token_score(a, b)
    return round(0.30 * raw + 0.70 * tok, 4)


# ---------------------------------------------------------------------------
# Registry: one per (tenant_id, domain). Pluggable seed loader.
# ---------------------------------------------------------------------------


class CanonicalRegistry:
    """In-memory canonical registry per (tenant_id, domain).

    The resolver consults the registry on every record. Discovery (new
    canonical mint) inserts into the same registry so subsequent records in
    the same run can hit it via exact match. State lives in memory for the
    process; persistence is a separate concern — for the demo, registries are
    seeded from the resolver caller (typically the orchestrator passes the
    "left" pipe's records as seeds before processing the "right" pipe).

    Aliases are stored as a parallel dict so an alias hit still resolves to
    the canonical entry.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], dict[str, CanonicalEntry]] = {}
        self._alias_to_canonical: dict[tuple[str, str], dict[str, str]] = {}
        self._pattern_rules: dict[tuple[str, str], list[PatternRule]] = {}

    def add_canonical(
        self, *, tenant_id: str, domain: str, value: str,
        canonical_id: Optional[str] = None, aliases: Optional[list[str]] = None,
    ) -> CanonicalEntry:
        """Add or return an existing canonical entry. Idempotent by normalized value."""
        if not tenant_id or not domain or not value:
            raise ValueError(
                f"add_canonical: tenant_id, domain, value required "
                f"(got tenant_id={tenant_id!r} domain={domain!r} value={value!r})"
            )
        key = (tenant_id, domain)
        bucket = self._entries.setdefault(key, {})
        norm = _normalize(value)
        if norm in bucket:
            return bucket[norm]
        cid = canonical_id or str(uuid.uuid4())
        entry = CanonicalEntry(canonical_id=cid, value=value, domain=domain,
                               aliases=list(aliases or []))
        bucket[norm] = entry
        alias_map = self._alias_to_canonical.setdefault(key, {})
        for alias in entry.aliases:
            alias_map[_normalize(alias)] = cid
        return entry

    def add_alias(self, *, tenant_id: str, domain: str, alias: str, canonical_id: str) -> None:
        if not alias or not canonical_id:
            raise ValueError("add_alias: alias and canonical_id required")
        self._alias_to_canonical.setdefault((tenant_id, domain), {})[_normalize(alias)] = canonical_id

    def add_pattern_rule(self, *, domain: str, pattern: str, canonical_id: str,
                         canonical_value: str, tenant_id: str) -> None:
        rule = PatternRule(domain=domain,
                           pattern=re.compile(pattern, re.IGNORECASE),
                           canonical_id=canonical_id,
                           canonical_value=canonical_value)
        self._pattern_rules.setdefault((tenant_id, domain), []).append(rule)

    def find_exact(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        return self._entries.get((tenant_id, domain), {}).get(_normalize(value))

    def find_alias(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        canonical_id = self._alias_to_canonical.get((tenant_id, domain), {}).get(_normalize(value))
        if not canonical_id:
            return None
        for entry in self._entries.get((tenant_id, domain), {}).values():
            if entry.canonical_id == canonical_id:
                return entry
        return None

    def find_pattern(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        for rule in self._pattern_rules.get((tenant_id, domain), []):
            if rule.pattern.search(value):
                bucket = self._entries.get((tenant_id, domain), {})
                for entry in bucket.values():
                    if entry.canonical_id == rule.canonical_id:
                        return entry
                # Canonical doesn't yet exist — synthesize one from the rule.
                entry = self.add_canonical(
                    tenant_id=tenant_id, domain=domain,
                    canonical_id=rule.canonical_id, value=rule.canonical_value,
                )
                return entry
        return None

    def iter_canonicals(self, *, tenant_id: str, domain: str) -> Iterable[CanonicalEntry]:
        return iter(self._entries.get((tenant_id, domain), {}).values())


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class RecordResolver:
    """The four-tier resolver. Lifts DCL's pattern, adapts inputs/outputs.

    Args:
      registry: CanonicalRegistry seeded by the caller (or empty for greenfield
                — in which case every record becomes a discovery).
      hitl_store_module: defaults to app.db.hitl_store. Swap for in-memory in
                tests.
      fuzzy_threshold: minimum similarity to accept any fuzzy match (default
                0.65, matching the WP3 operator-visible outcome — the FinTeam-NA
                vs Finance North America case scores ~0.67). Below this, the
                record is rejected loudly.
      auto_threshold: similarity >= this auto-accepts as a fuzzy match. The band
                [fuzzy_threshold, auto_threshold) is HITL-pending.
      discovery_enabled: if True, no-match records mint a new canonical_id at
                method='discovery'. If False, no-match -> rejected.
    """

    def __init__(
        self,
        registry: CanonicalRegistry,
        *,
        hitl_store_module: Any = hitl_store,
        fuzzy_threshold: float = 0.65,
        auto_threshold: float = 0.90,
        discovery_enabled: bool = True,
    ) -> None:
        if not (0.0 <= fuzzy_threshold <= auto_threshold <= 1.0):
            raise ValueError(
                f"RecordResolver: thresholds must satisfy 0 <= fuzzy <= auto <= 1 "
                f"(got fuzzy={fuzzy_threshold} auto={auto_threshold})"
            )
        self.registry = registry
        self.hitl = hitl_store_module
        self.fuzzy_threshold = fuzzy_threshold
        self.auto_threshold = auto_threshold
        self.discovery_enabled = discovery_enabled

    def resolve(
        self,
        record: dict,
        *,
        domain: str,
        pipe_id: str,
        tenant_id: str,
        entity_id: str,
        value_field: str,
        record_key_field: str = "id",
        compare_against: Optional[Callable[[CanonicalEntry], list[str]]] = None,
    ) -> ResolutionResult:
        """Resolve one record's identity to a canonical_id.

        record: the raw record dict (e.g., a NetSuite vendor row).
        value_field: which field in `record` carries the human-readable value
                     to resolve against (e.g., "vendor_name").
        record_key_field: which field is the source-system natural key
                          (e.g., "vendor_id"). Stored for audit.
        compare_against: optional fn returning the set of strings to compare
                         this record's value against per canonical entry
                         (defaults to [entry.value] + entry.aliases). Use for
                         multi-name canonicals (e.g., compare against both
                         display_name and short_name on the right pipe).
        """
        if not tenant_id or not entity_id:
            raise ValueError(
                f"resolve: tenant_id and entity_id required "
                f"(got tenant_id={tenant_id!r} entity_id={entity_id!r})"
            )
        if not domain:
            raise ValueError("resolve: domain required (e.g., 'saas_subscription', 'cost_center')")
        raw_value = record.get(value_field)
        if raw_value is None or str(raw_value).strip() == "":
            raise ValueError(
                f"resolve: record missing required value_field={value_field!r} "
                f"(record keys: {list(record.keys())})"
            )
        value = str(raw_value)
        record_key = str(record.get(record_key_field) or "")

        # Tier 1: exact normalized match
        exact = self.registry.find_exact(tenant_id=tenant_id, domain=domain, value=value)
        if exact:
            return ResolutionResult(
                canonical_id=exact.canonical_id,
                resolution_method="exact",
                resolution_confidence=1.0,
                audit={"matched_value": exact.value, "input_value": value},
            )

        # Tier 2: alias
        alias = self.registry.find_alias(tenant_id=tenant_id, domain=domain, value=value)
        if alias:
            return ResolutionResult(
                canonical_id=alias.canonical_id,
                resolution_method="alias",
                resolution_confidence=0.95,
                audit={"matched_via_alias_for": alias.value, "input_value": value},
            )

        # Tier 3: pattern
        pattern_hit = self.registry.find_pattern(tenant_id=tenant_id, domain=domain, value=value)
        if pattern_hit:
            return ResolutionResult(
                canonical_id=pattern_hit.canonical_id,
                resolution_method="pattern",
                resolution_confidence=0.85,
                audit={"matched_via_pattern_to": pattern_hit.value, "input_value": value},
            )

        # Tier 4: fuzzy — scan the registry, pick highest score
        best_entry: Optional[CanonicalEntry] = None
        best_score = 0.0
        for entry in self.registry.iter_canonicals(tenant_id=tenant_id, domain=domain):
            candidate_strings = (compare_against(entry) if compare_against
                                 else [entry.value] + list(entry.aliases))
            for cand in candidate_strings:
                score = similarity_score(value, cand)
                if score > best_score:
                    best_score = score
                    best_entry = entry

        if best_entry and best_score >= self.auto_threshold:
            return ResolutionResult(
                canonical_id=best_entry.canonical_id,
                resolution_method="fuzzy",
                resolution_confidence=round(best_score, 4),
                audit={"matched_to": best_entry.value, "input_value": value,
                       "raw_score": best_score},
            )

        if best_entry and best_score >= self.fuzzy_threshold:
            # HITL — queue and tag pending.
            proposed_canonical_id = best_entry.canonical_id
            hitl_id = self.hitl.insert_pending(
                tenant_id=tenant_id,
                entity_id=entity_id,
                domain=domain,
                left_pipe_id=pipe_id,
                left_record_key=record_key,
                left_value=value,
                right_pipe_id=None,
                right_record_key=None,
                right_value=best_entry.value,
                confidence=round(best_score, 4),
                proposed_canonical_id=proposed_canonical_id,
                extra={
                    "input_value": value,
                    "candidate_value": best_entry.value,
                    "raw_score": best_score,
                },
            )
            return ResolutionResult(
                canonical_id=proposed_canonical_id,
                resolution_method="hitl_pending",
                resolution_confidence=round(best_score, 4),
                hitl_queue_id=hitl_id,
                audit={"matched_to": best_entry.value, "input_value": value,
                       "raw_score": best_score},
            )

        # No match: discovery (mint) or rejected.
        if self.discovery_enabled:
            new_entry = self.registry.add_canonical(
                tenant_id=tenant_id, domain=domain, value=value,
            )
            return ResolutionResult(
                canonical_id=new_entry.canonical_id,
                resolution_method="discovery",
                resolution_confidence=0.99,
                audit={"minted_canonical_for": value, "best_lookup_score": best_score},
            )

        return ResolutionResult(
            canonical_id=None,
            resolution_method="rejected",
            resolution_confidence=round(best_score, 4),
            audit={
                "input_value": value,
                "best_candidate": best_entry.value if best_entry else None,
                "best_score": best_score,
                "reason": "no candidate above fuzzy_threshold, discovery disabled",
            },
        )
