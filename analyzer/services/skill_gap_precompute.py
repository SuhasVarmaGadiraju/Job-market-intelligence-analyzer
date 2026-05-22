from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.core.cache import cache
from analyzer.services.jobs_api import fetch_live_jobs_from_api

_CACHE_KEY = "skill_gap:role_skill_index:live:"
_CACHE_TTL_SECONDS = 3600  # 1 hour minimum cache

@dataclass(frozen=True)
class RoleSkillClassification:
    role: str
    total_jobs: int
    core: List[str]
    important: List[str]
    optional: List[str]
    note: str

# Curated lightweight role list for autocomplete and options
POPULAR_ROLES = [
    "Software Engineer",
    "Data Scientist",
    "DevOps Engineer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Product Manager",
    "UI/UX Designer",
    "Data Engineer",
    "Cloud Engineer",
    "Mobile App Developer",
    "Systems Architect",
    "Cybersecurity Analyst",
    "QA Engineer",
    "Machine Learning Engineer",
    "AI Engineer",
    "Business Analyst",
    "Database Administrator",
    "Network Engineer",
    "Scrum Master",
    "Project Manager",
    "Solution Architect"
]

def role_options() -> List[str]:
    """Return lightweight predefined popular roles list."""
    return POPULAR_ROLES

def get_role_classification(role: str) -> Optional[RoleSkillClassification]:
    """
    On-demand Live API-driven role skill classification.
    Fetches live JSearch jobs, parses skills, and categorizes them.
    Cached for 1 hour.
    """
    if not role:
        return None
        
    cache_key = f"{_CACHE_KEY}{role.lower().strip().replace(' ', '_')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch live jobs from the JSearch API
    jobs = fetch_live_jobs_from_api(role)
    if not jobs:
        return RoleSkillClassification(
            role=role,
            total_jobs=0,
            core=[],
            important=[],
            optional=[],
            note="No live jobs found for this role."
        )

    # Calculate skill counts and job counts
    total_jobs = len(jobs)
    skill_counts: Counter = Counter()
    
    for job in jobs:
        skills_str = job.get("skills", "")
        # Parse out individual skills
        skills = [s.strip().lower() for s in skills_str.split(",") if s.strip()]
        skill_counts.update(skills)

    core: List[str] = []
    important: List[str] = []
    optional: List[str] = []

    for name, cnt in skill_counts.items():
        pct = (cnt / total_jobs) * 100.0
        if pct >= 60.0:
            core.append(name.title())
        elif pct >= 25.0:
            important.append(name.title())
        else:
            optional.append(name.title())

    # Fallback to ensure there are always some core skills
    note = ""
    if not core and skill_counts:
        top_skills = [name.title() for name, _ in skill_counts.most_common(5)]
        core = top_skills
        important = [n for n in important if n not in set(top_skills)]
        optional = [n for n in optional if n not in set(top_skills)]
        note = "Core skills inferred from most frequent skills due to low consensus across postings."

    classification = RoleSkillClassification(
        role=role,
        total_jobs=total_jobs,
        core=core,
        important=important,
        optional=optional,
        note=note
    )

    cache.set(cache_key, classification, _CACHE_TTL_SECONDS)
    return classification

def warm_role_skill_index() -> None:
    """Pre-computations are now done on-demand, this is a fast no-op."""
    pass
