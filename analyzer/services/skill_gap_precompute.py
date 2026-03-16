from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.core.cache import cache

from analyzer.models import Job


_CACHE_KEY = "skill_gap:role_skill_index:v2"
_CACHE_TTL_SECONDS = 60 * 60


@dataclass(frozen=True)
class RoleSkillClassification:
    role: str
    total_jobs: int
    core: List[str]
    important: List[str]
    optional: List[str]
    note: str


_role_classification: Dict[str, RoleSkillClassification] = {}
_role_options: List[str] = []


def role_options() -> List[str]:
    return _role_options


def get_role_classification(role: str) -> Optional[RoleSkillClassification]:
    if not role:
        return None
    return _role_classification.get(role)


def warm_role_skill_index() -> None:
    global _role_classification, _role_options

    cached = cache.get(_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("role_options") and cached.get("roles"):
        _role_options = cached["role_options"]
        _role_classification = cached["roles"]
        return

    roles, options = _build_role_skill_index_from_db()
    _role_classification = roles
    _role_options = options

    cache.set(
        _CACHE_KEY,
        {"role_options": _role_options, "roles": _role_classification},
        _CACHE_TTL_SECONDS,
    )


def _normalize_skill_tokens(skills_str: str) -> Tuple[str, ...]:
    if not skills_str:
        return tuple()
    s = skills_str.lower()
    for ch in ["\n", "\r", ";", "|", "/", "•"]:
        s = s.replace(ch, ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return tuple(dict.fromkeys(parts).keys())


def _classify_skills(total_jobs: int, skill_counts: Counter) -> Tuple[List[str], List[str], List[str], str]:
    if total_jobs < 5:
        top = [name.title() for name, _ in skill_counts.most_common(5)]
        return top, [], [], "Not enough data for detailed skill classification."

    core: List[str] = []
    important: List[str] = []
    optional: List[str] = []

    for name, cnt in skill_counts.items():
        pct = (cnt / total_jobs) * 100.0
        if pct >= 60.0:
            core.append(name)
        elif pct >= 25.0:
            important.append(name)
        else:
            optional.append(name)

    core.sort(key=lambda n: skill_counts[n], reverse=True)
    important.sort(key=lambda n: skill_counts[n], reverse=True)
    optional.sort(key=lambda n: skill_counts[n], reverse=True)

    note = ""
    if not core and skill_counts:
        # Fallback: if no skill appears in >=60% of jobs, still provide a practical
        # 'core' list from the most frequent skills so gap calculations never show 0/0.
        inferred_core = [name for name, _ in skill_counts.most_common(5)]
        core = inferred_core
        important = [n for n in important if n not in set(inferred_core)]
        optional = [n for n in optional if n not in set(inferred_core)]
        note = "Core skills inferred from most frequent skills due to low consensus across job postings."

    return (
        [n.title() for n in core],
        [n.title() for n in important],
        [n.title() for n in optional],
        note,
    )


def _build_role_skill_index_from_db() -> Tuple[Dict[str, RoleSkillClassification], List[str]]:
    role_job_counts: Counter = Counter()
    role_skill_counts: Dict[str, Counter] = defaultdict(Counter)

    qs = (
        Job.objects.exclude(title__isnull=True)
        .exclude(title__exact="")
        .values_list("title", "skills")
        .iterator(chunk_size=2000)
    )

    for title, skills_str in qs:
        role_job_counts[title] += 1
        tokens = _normalize_skill_tokens(skills_str or "")
        if tokens:
            role_skill_counts[title].update(tokens)

    roles: Dict[str, RoleSkillClassification] = {}

    for title, total in role_job_counts.items():
        counts = role_skill_counts.get(title) or Counter()
        core, important, optional, note = _classify_skills(total, counts)
        roles[title] = RoleSkillClassification(
            role=title,
            total_jobs=total,
            core=core,
            important=important,
            optional=optional,
            note=note,
        )

    options = sorted(roles.keys())
    return roles, options
