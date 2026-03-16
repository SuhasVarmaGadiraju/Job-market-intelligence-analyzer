from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple

from django.core.cache import cache

from analyzer.models import Job


_CACHE_KEY = "salary_insights:role_salary_index:v1"
_CACHE_TTL_SECONDS = 60 * 60


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


_role_salary_index: Dict[str, SalaryInsights] = {}


def get_salary_insights(role: str) -> Optional[SalaryInsights]:
    if not role:
        return None
    # Safety: if this module is imported before AppConfig.ready() runs,
    # warm from cache/DB on first access.
    if not _role_salary_index:
        warm_salary_insights_index()
    return _role_salary_index.get(role)


def warm_salary_insights_index() -> None:
    global _role_salary_index

    cached = cache.get(_CACHE_KEY)
    if isinstance(cached, dict) and cached:
        _role_salary_index = cached
        return

    _role_salary_index = _build_salary_index_from_db()
    cache.set(_CACHE_KEY, _role_salary_index, _CACHE_TTL_SECONDS)


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    values_sorted = sorted(values)
    n = len(values_sorted)
    mid = n // 2
    if n % 2 == 1:
        return float(values_sorted[mid])
    return float((values_sorted[mid - 1] + values_sorted[mid]) / 2.0)


def _parse_experience_years(exp_raw: str) -> Optional[float]:
    if not exp_raw:
        return None
    t = exp_raw.lower().strip()

    # Common patterns: "0-2", "2-5", "5+", "3 years", "3-5 years", "1+"
    nums: List[float] = []
    buf = ""
    for ch in t:
        if ch.isdigit() or ch == ".":
            buf += ch
        else:
            if buf:
                try:
                    nums.append(float(buf))
                except ValueError:
                    pass
                buf = ""
    if buf:
        try:
            nums.append(float(buf))
        except ValueError:
            pass

    if not nums:
        return None

    if "+" in t:
        return max(nums)

    # pick midpoint when range exists
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2.0

    return nums[0]


def _experience_band(years: Optional[float]) -> str:
    if years is None:
        return "Unknown"
    if years <= 2:
        return "0–2 years"
    if years <= 5:
        return "2–5 years"
    return "5+ years"


def _normalize_skill_tokens(skills_str: str) -> Tuple[str, ...]:
    if not skills_str:
        return tuple()
    s = skills_str.lower()
    for ch in ["\n", "\r", ";", "|", "/", "•"]:
        s = s.replace(ch, ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    # dedupe while preserving order
    return tuple(dict.fromkeys(parts).keys())


def _clean_city(location: str) -> str:
    if not location:
        return "Unknown"
    loc = location.strip()
    if not loc:
        return "Unknown"
    # Keep the first comma-separated segment as a "city" heuristic
    return loc.split(",")[0].strip() or "Unknown"


def _build_salary_index_from_db() -> Dict[str, SalaryInsights]:
    salaries_by_role: DefaultDict[str, List[float]] = defaultdict(list)

    # Aggregates for salary-by-experience
    exp_sum: DefaultDict[str, DefaultDict[str, float]] = defaultdict(lambda: defaultdict(float))
    exp_cnt: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Aggregates for salary-by-city
    city_sum: DefaultDict[str, DefaultDict[str, float]] = defaultdict(lambda: defaultdict(float))
    city_cnt: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Aggregates for skill salary lift
    role_total_sum: DefaultDict[str, float] = defaultdict(float)
    role_total_cnt: DefaultDict[str, int] = defaultdict(int)
    skill_sum: DefaultDict[str, DefaultDict[str, float]] = defaultdict(lambda: defaultdict(float))
    skill_cnt: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))

    qs = (
        Job.objects.exclude(title__isnull=True)
        .exclude(title__exact="")
        .exclude(final_salary__isnull=True)
        .filter(final_salary__gt=0)
        .values_list("title", "final_salary", "experience", "location", "skills")
        .iterator(chunk_size=2000)
    )

    for title, salary, exp_raw, location, skills_str in qs:
        try:
            sal = float(salary)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(sal) or sal <= 0:
            continue

        role = title
        salaries_by_role[role].append(sal)
        role_total_sum[role] += sal
        role_total_cnt[role] += 1

        band = _experience_band(_parse_experience_years((exp_raw or "").strip()))
        exp_sum[role][band] += sal
        exp_cnt[role][band] += 1

        city = _clean_city(location or "")
        city_sum[role][city] += sal
        city_cnt[role][city] += 1

        tokens = _normalize_skill_tokens(skills_str or "")
        if tokens:
            for tok in tokens:
                skill_sum[role][tok] += sal
                skill_cnt[role][tok] += 1

    index: Dict[str, SalaryInsights] = {}

    exp_order = ["0–2 years", "2–5 years", "5+ years", "Unknown"]

    for role, salaries in salaries_by_role.items():
        if not salaries:
            continue

        total = len(salaries)
        min_salary = float(min(salaries)) if salaries else None
        max_salary = float(max(salaries)) if salaries else None
        avg_salary = float(sum(salaries) / total) if total else None
        median_salary = _median(salaries)

        # salary by experience
        by_exp: List[Dict[str, Any]] = []
        for band in exp_order:
            cnt = exp_cnt[role].get(band, 0)
            if cnt <= 0:
                continue
            by_exp.append({
                "band": band,
                "avg_salary": round(exp_sum[role][band] / cnt, 0),
                "jobs": cnt,
            })

        # top cities
        cities: List[Tuple[str, float, int]] = []
        for city, cnt in city_cnt[role].items():
            if cnt < 3:
                continue
            cities.append((city, city_sum[role][city] / cnt, cnt))
        cities.sort(key=lambda t: t[1], reverse=True)
        top_cities = [
            {"city": city, "avg_salary": round(avg, 0), "jobs": cnt}
            for city, avg, cnt in cities[:5]
        ]

        # skills that increase salary
        skills_lift: List[Dict[str, Any]] = []
        total_sum = role_total_sum[role]
        total_cnt = role_total_cnt[role]

        for skill, cnt_with in skill_cnt[role].items():
            if cnt_with < 5:
                continue
            sum_with = skill_sum[role][skill]
            cnt_without = total_cnt - cnt_with
            if cnt_without < 5:
                continue

            avg_with = sum_with / cnt_with
            avg_without = (total_sum - sum_with) / cnt_without if cnt_without else None
            if not avg_without or avg_without <= 0:
                continue

            impact_pct = ((avg_with - avg_without) / avg_without) * 100.0
            if impact_pct <= 0:
                continue

            skills_lift.append({
                "skill": skill.title(),
                "boost_percent": round(impact_pct, 1),
                "avg_salary_with": round(avg_with, 0),
                "avg_salary_without": round(avg_without, 0),
                "jobs_with_skill": int(cnt_with),
            })

        skills_lift.sort(key=lambda x: x["boost_percent"], reverse=True)
        skills_lift = skills_lift[:10]

        index[role] = SalaryInsights(
            role=role,
            total_jobs_with_salary=total,
            min_salary=round(min_salary, 0) if min_salary is not None else None,
            avg_salary=round(avg_salary, 0) if avg_salary is not None else None,
            max_salary=round(max_salary, 0) if max_salary is not None else None,
            median_salary=round(median_salary, 0) if median_salary is not None else None,
            salary_by_experience=by_exp,
            top_cities=top_cities,
            skills_that_increase_salary=skills_lift,
        )

    return index
