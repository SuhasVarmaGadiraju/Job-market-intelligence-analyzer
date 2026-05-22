from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

from django.core.cache import cache
from analyzer.services.jobs_api import fetch_live_jobs_from_api

_CACHE_KEY = "salary_insights:role_salary_index:live:"
_CACHE_TTL_SECONDS = 3600  # 1 hour minimum cache

@dataclass(frozen=True)
class SalaryInsights:
    role: str
    total_jobs_with_salary: int
    min_salary: Optional[float]
    avg_salary: Optional[float]
    max_salary: Optional[float]
    median_salary: Optional[float]
    salary_by_experience: List[Dict[str, Any]]
    top_cities: List[Dict[str, Any]]
    skills_that_increase_salary: List[Dict[str, Any]]

def get_salary_insights(role: str) -> Optional[SalaryInsights]:
    """
    On-demand JSearch API-driven salary insights.
    Fetches live jobs, processes experience, location, and skills in-memory.
    Cached for 1 hour.
    """
    if not role:
        return None

    cache_key = f"{_CACHE_KEY}{role.lower().strip().replace(' ', '_')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch live jobs from our API service
    jobs = fetch_live_jobs_from_api(role)
    if not jobs:
        insights = SalaryInsights(
            role=role,
            total_jobs_with_salary=0,
            min_salary=None,
            avg_salary=None,
            max_salary=None,
            median_salary=None,
            salary_by_experience=[],
            top_cities=[],
            skills_that_increase_salary=[]
        )
        cache.set(cache_key, insights, _CACHE_TTL_SECONDS)
        return insights

    salaries = []
    exp_sum = defaultdict(float)
    exp_cnt = defaultdict(int)
    city_sum = defaultdict(float)
    city_cnt = defaultdict(int)
    skill_sum = defaultdict(float)
    skill_cnt = defaultdict(int)

    total_sum = 0.0
    total_cnt = 0

    for job in jobs:
        salary = job.get("final_salary")
        if not salary or salary <= 0:
            continue

        sal = float(salary)
        salaries.append(sal)
        total_sum += sal
        total_cnt += 1

        # Experience band
        exp_raw = job.get("experience", "Unknown")
        band = _experience_band(_parse_experience_years(exp_raw))
        exp_sum[band] += sal
        exp_cnt[band] += 1

        # City / Location
        city = _clean_city(job.get("location", "Unknown"))
        city_sum[city] += sal
        city_cnt[city] += 1

        # Skills
        skills_str = job.get("skills", "")
        skills = [s.strip().lower() for s in skills_str.split(",") if s.strip()]
        for skill in set(skills):
            skill_sum[skill] += sal
            skill_cnt[skill] += 1

    if not salaries:
        insights = SalaryInsights(
            role=role,
            total_jobs_with_salary=0,
            min_salary=None,
            avg_salary=None,
            max_salary=None,
            median_salary=None,
            salary_by_experience=[],
            top_cities=[],
            skills_that_increase_salary=[]
        )
        cache.set(cache_key, insights, _CACHE_TTL_SECONDS)
        return insights

    min_sal = min(salaries)
    max_sal = max(salaries)
    avg_sal = sum(salaries) / len(salaries)
    med_sal = _median(salaries)

    # Salary by experience
    exp_order = ["0–2 years", "2–5 years", "5+ years", "Unknown"]
    salary_by_exp = []
    for band in exp_order:
        cnt = exp_cnt[band]
        if cnt > 0:
            salary_by_exp.append({
                "band": band,
                "avg_salary": round(exp_sum[band] / cnt, 0),
                "jobs": cnt
            })

    # Top cities
    cities = []
    for city, cnt in city_cnt.items():
        if city != "Unknown" and cnt > 0:
            cities.append((city, city_sum[city] / cnt, cnt))
    cities.sort(key=lambda x: x[1], reverse=True)
    top_cities = [
        {"city": city.title(), "avg_salary": round(avg, 0), "jobs": cnt}
        for city, avg, cnt in cities[:5]
    ]

    # Skills boost
    skills_lift = []
    for skill, cnt_with in skill_cnt.items():
        if cnt_with >= 2:
            sum_with = skill_sum[skill]
            cnt_without = total_cnt - cnt_with
            
            avg_with = sum_with / cnt_with
            avg_without = (total_sum - sum_with) / cnt_without if cnt_without > 0 else avg_sal
            
            if avg_without > 0:
                impact_pct = ((avg_with - avg_without) / avg_without) * 100.0
                if impact_pct > 0:
                    skills_lift.append({
                        "skill": skill.title(),
                        "boost_percent": round(impact_pct, 1),
                        "avg_salary_with": round(avg_with, 0),
                        "avg_salary_without": round(avg_without, 0),
                        "jobs_with_skill": int(cnt_with)
                    })

    skills_lift.sort(key=lambda x: x["boost_percent"], reverse=True)

    insights = SalaryInsights(
        role=role,
        total_jobs_with_salary=len(salaries),
        min_salary=round(min_sal, 0),
        avg_salary=round(avg_sal, 0),
        max_salary=round(max_sal, 0),
        median_salary=round(med_sal, 0) if med_sal is not None else round(avg_sal, 0),
        salary_by_experience=salary_by_exp,
        top_cities=top_cities,
        skills_that_increase_salary=skills_lift[:10]
    )

    cache.set(cache_key, insights, _CACHE_TTL_SECONDS)
    return insights

def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)

def _parse_experience_years(exp_raw: str) -> Optional[float]:
    if not exp_raw:
        return None
    t = exp_raw.lower().strip()
    nums = re.findall(r"\d+(?:\.\d+)?", t)
    if not nums:
        return None
    try:
        values = [float(n) for n in nums]
    except ValueError:
        return None
    if "+" in t:
        return max(values)
    if len(values) >= 2:
        return (values[0] + values[1]) / 2.0
    return values[0]

def _experience_band(years: Optional[float]) -> str:
    if years is None:
        return "Unknown"
    if years <= 2:
        return "0–2 years"
    if years <= 5:
        return "2–5 years"
    return "5+ years"

def _clean_city(location: str) -> str:
    if not location:
        return "Unknown"
    loc = location.strip()
    if not loc:
        return "Unknown"
    return loc.split(",")[0].strip() or "Unknown"

def warm_salary_insights_index() -> None:
    """Pre-computations are now on-demand. Fast no-op."""
    pass
