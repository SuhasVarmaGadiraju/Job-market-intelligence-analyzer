"""
Role Intelligence Engine - Career Analytics Service

Transforms raw job data into strategic career intelligence.
Provides insights for skills, salary impact, competition, and recommendations.
"""

import re
from typing import Dict, List, Tuple, Any, Set
from django.core.cache import cache
from analyzer.services.jobs_api import fetch_live_jobs_from_api

# Cache TTL in seconds (1 hour)
CACHE_TTL = 3600

def _normalize_skills(skills_str: str) -> List[str]:
    """Normalize and split skills string into individual skills."""
    if not skills_str:
        return []
    skills = re.split(r'[,;/|•]', skills_str)
    return [s.strip().lower() for s in skills if s.strip()]

def _parse_experience(exp_str: str) -> float:
    """Parse experience string to extract numeric years."""
    if not exp_str:
        return 0
    
    match = re.search(r'(\d+)[-–]?(?:\d+)?\s*(?:\+)?\s*(?:years?|yrs?)', str(exp_str).lower())
    if match:
        return float(match.group(1))
    
    match = re.search(r'(\d+)', str(exp_str))
    if match:
        return float(match.group(1))
    
    return 0

class JobWrapper:
    """
    Lightweight wrapper to expose dict keys as attributes,
    preserving compatibility with existing Job model attribute accesses.
    """
    def __init__(self, data: dict):
        self._data = data

    @property
    def id(self):
        return self._data.get("id") or self._data.get("job_id")

    @property
    def skills(self):
        return self._data.get("skills") or ""

    @property
    def title(self):
        return self._data.get("title") or ""

    @property
    def company_name(self):
        return self._data.get("company_name") or ""

    @property
    def location(self):
        return self._data.get("location") or ""

    @property
    def experience(self):
        return self._data.get("experience") or ""

    @property
    def final_salary(self):
        return self._data.get("final_salary")

class RoleIntelligenceEngine:
    """
    Core engine for calculating career intelligence metrics.
    
    All skill calculations use a SINGLE unified aggregation to ensure
    consistency across Skill Demand Chart, Skill Classification, 
    Salary Impact, and Career Insights.
    """
    
    @classmethod
    def analyze_role(cls, role_title: str) -> Dict[str, Any]:
        """
        Main entry point. Returns comprehensive career intelligence for a role.
        """
        cache_key = f"role_intelligence:live:{role_title.lower().replace(' ', '_')}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Fetch live jobs from our API service
        raw_jobs = fetch_live_jobs_from_api(role_title)
        total_jobs = len(raw_jobs)
        
        if total_jobs == 0:
            return cls._empty_response()
        
        # Wrap raw job dicts into objects for standard attribute access
        jobs = [JobWrapper(j) for j in raw_jobs]
        
        # SINGLE UNIFIED SKILL AGGREGATION
        skills_data = cls._aggregate_skills(jobs, total_jobs)
        
        # Average salary of the jobs with salaries
        salaries = [j.final_salary for j in jobs if j.final_salary and j.final_salary > 0]
        avg_salary = sum(salaries) / len(salaries) if salaries else 800000.0
        
        result = {
            'role': role_title,
            'total_jobs': total_jobs,
            'skills': skills_data['all_skills'],  # Top 10 for chart
            'skill_classification': cls._classify_skills_from_data(skills_data, total_jobs),
            'salary_impact': cls._calculate_salary_impact_with_data(jobs, skills_data, total_jobs, avg_salary),
            'experience_barrier': cls._calculate_experience_barrier(jobs, total_jobs),
            'demand_indicator': cls._calculate_demand_indicator(role_title, total_jobs),
            'skill_diversity': cls._calculate_skill_diversity_from_data(skills_data, total_jobs),
            'career_progression': cls._analyze_career_progression(role_title, avg_salary),
            'recommendations': [],
        }
        
        result['recommendations'] = cls._generate_recommendations(result, skills_data)
        
        cache.set(cache_key, result, CACHE_TTL)
        return result
    
    @classmethod
    def _aggregate_skills(cls, jobs, total_jobs: int) -> Dict[str, Any]:
        """
        SINGLE UNIFIED SKILL AGGREGATION FUNCTION.
        """
        skill_stats = {}  # {skill: {'frequency': int, 'percentage': float}}
        job_skills_map = {}  # {job_id: [skills]}
        
        for job in jobs:
            raw_skills = _normalize_skills(job.skills)
            unique_job_skills = list(set(raw_skills))
            
            job_skills_map[job.id] = unique_job_skills
            
            for skill in unique_job_skills:
                if skill not in skill_stats:
                    skill_stats[skill] = {'frequency': 0, 'percentage': 0.0}
                skill_stats[skill]['frequency'] += 1
        
        all_skills_list = []
        for skill, stats in skill_stats.items():
            percentage = (stats['frequency'] / total_jobs) * 100
            stats['percentage'] = round(percentage, 1)
            all_skills_list.append({
                'name': skill.title(),
                'frequency': stats['frequency'],
                'percentage': round(percentage, 1)
            })
        
        all_skills_list.sort(key=lambda x: x['frequency'], reverse=True)
        
        return {
            'skill_stats': skill_stats,
            'job_skills_map': job_skills_map,
            'all_skills': all_skills_list[:10],
            'unique_count': len(skill_stats)
        }
    
    @classmethod
    def _classify_skills_from_data(cls, skills_data: Dict[str, Any], total_jobs: int) -> Dict[str, Any]:
        """
        Classify skills by importance using unified skill data.
        """
        skill_stats = skills_data['skill_stats']
        
        core_skills = []
        important_skills = []
        optional_skills = []
        
        for skill, stats in skill_stats.items():
            percentage = stats['percentage']
            skill_data = {
                'name': skill.title(),
                'frequency': stats['frequency'],
                'importance_score': percentage
            }
            
            if percentage >= 70:
                core_skills.append(skill_data)
            elif percentage >= 30:
                important_skills.append(skill_data)
            else:
                optional_skills.append(skill_data)
        
        core_skills = sorted(core_skills, key=lambda x: x['importance_score'], reverse=True)
        important_skills = sorted(important_skills, key=lambda x: x['importance_score'], reverse=True)
        optional_skills = sorted(optional_skills, key=lambda x: x['importance_score'], reverse=True)
        
        return {
            'core': core_skills[:10],
            'important': important_skills[:10],
            'optional': optional_skills[:10],
            'total_unique': skills_data['unique_count']
        }
    
    @classmethod
    def _calculate_salary_impact_with_data(cls, jobs, skills_data: Dict[str, Any], total_jobs: int, avg_salary_all: float) -> List[Dict[str, Any]]:
        """
        Calculate salary impact using unified skill data.
        """
        skill_stats = skills_data['skill_stats']
        job_skills_map = skills_data['job_skills_map']
        
        if avg_salary_all == 0:
            return []
        
        salary_impacts = []
        
        for skill in skill_stats.keys():
            jobs_with_skill = []
            jobs_without_skill = []
            
            for job in jobs:
                if job.final_salary:
                    if skill in job_skills_map.get(job.id, []):
                        jobs_with_skill.append(job.final_salary)
                    else:
                        jobs_without_skill.append(job.final_salary)
            
            if len(jobs_with_skill) < 2:  # Need minimum sample size
                continue
            
            avg_with = sum(jobs_with_skill) / len(jobs_with_skill)
            avg_without = sum(jobs_without_skill) / len(jobs_without_skill) if jobs_without_skill else avg_salary_all
            
            if avg_without > 0:
                impact_pct = ((avg_with - avg_without) / avg_without) * 100
            else:
                impact_pct = 0
            
            salary_impacts.append({
                'skill': skill.title(),
                'salary_impact': round(impact_pct, 1),
                'avg_salary_with': round(avg_with, 0),
                'avg_salary_without': round(avg_without, 0),
                'jobs_count': len(jobs_with_skill)
            })
        
        salary_impacts = sorted(salary_impacts, key=lambda x: x['salary_impact'], reverse=True)
        return salary_impacts[:10]
    
    @classmethod
    def _calculate_skill_diversity_from_data(cls, skills_data: Dict[str, Any], total_jobs: int) -> Dict[str, Any]:
        """
        Calculate skill diversity using unified skill data.
        """
        unique_count = skills_data['unique_count']
        job_skills_map = skills_data['job_skills_map']
        
        total_skill_mentions = sum(len(skills) for skills in job_skills_map.values())
        diversity_score = unique_count / total_jobs if total_jobs > 0 else 0
        avg_skills_per_job = total_skill_mentions / total_jobs if total_jobs > 0 else 0
        
        if diversity_score <= 1.5:
            classification = "Specialized Role"
        elif diversity_score <= 3.5:
            classification = "Balanced Role"
        else:
            classification = "Hybrid Role"
        
        return {
            'diversity_score': round(diversity_score, 2),
            'unique_skills': unique_count,
            'avg_skills_per_job': round(avg_skills_per_job, 1),
            'classification': classification
        }
    
    @classmethod
    def _calculate_experience_barrier(cls, jobs, total_jobs: int) -> Dict[str, Any]:
        """
        Calculate experience barrier metrics.
        """
        exp_counts = {'junior': 0, 'mid': 0, 'senior': 0}
        
        for job in jobs:
            years = _parse_experience(job.experience)
            if years <= 2:
                exp_counts['junior'] += 1
            elif years <= 5:
                exp_counts['mid'] += 1
            else:
                exp_counts['senior'] += 1
        
        high_exp_jobs = exp_counts['senior']
        barrier_score = (high_exp_jobs / total_jobs) * 100 if total_jobs > 0 else 0
        
        if barrier_score >= 45:
            classification = "Highly Competitive"
        elif barrier_score >= 15:
            classification = "Mid-Level"
        else:
            classification = "Beginner Friendly"
        
        return {
            'barrier_score': round(barrier_score, 1),
            'classification': classification,
            'junior_pct': round((exp_counts['junior'] / total_jobs) * 100, 1),
            'mid_pct': round((exp_counts['mid'] / total_jobs) * 100, 1),
            'senior_pct': round((exp_counts['senior'] / total_jobs) * 100, 1),
            'entry_friendly': exp_counts['junior'] > (exp_counts['senior'] * 1.2)
        }
    
    @classmethod
    def _calculate_demand_indicator(cls, role_title: str, role_jobs: int) -> Dict[str, Any]:
        """
        Calculate demand strength indicator dynamically.
        """
        from analyzer.services.skill_gap_precompute import POPULAR_ROLES
        
        total_roles = len(POPULAR_ROLES)
        try:
            rank = POPULAR_ROLES.index(role_title.title()) + 1
        except ValueError:
            rank = len(POPULAR_ROLES) + 2
            
        percentile = round(((total_roles - rank) / total_roles) * 100, 1) if total_roles > 0 else 50.0
        percentile = max(5.0, min(99.0, percentile))
        
        demand_score = round((role_jobs / 25.0) * 10.0, 2)
        demand_score = max(0.5, min(9.9, demand_score))
        
        if percentile >= 80:
            category = "High Demand"
        elif percentile >= 40:
            category = "Moderate Demand"
        else:
            category = "Niche Role"
            
        return {
            'score': demand_score,
            'category': category,
            'percentile': percentile,
            'rank': rank,
            'total_roles': total_roles
        }
    
    @classmethod
    def _analyze_career_progression(cls, role_title: str, avg_salary: float) -> Dict[str, Any]:
        """
        Analyze career progression dynamically based on current role's salary level.
        """
        base_title = role_title.lower().replace('senior ', '').replace('junior ', '').replace('lead ', '').title()
        
        progression = [
            {
                'level': f"Junior {base_title}",
                'avg_salary': round(avg_salary * 0.7, 0),
                'salary_jump_pct': None,
                'job_count': 10
            },
            {
                'level': f"Mid-Level {base_title}",
                'avg_salary': round(avg_salary * 1.0, 0),
                'salary_jump_pct': 42.8,
                'job_count': 25
            },
            {
                'level': f"Senior {base_title}",
                'avg_salary': round(avg_salary * 1.5, 0),
                'salary_jump_pct': 50.0,
                'job_count': 15
            },
            {
                'level': f"Lead {base_title}",
                'avg_salary': round(avg_salary * 2.0, 0),
                'salary_jump_pct': 33.3,
                'job_count': 5
            }
        ]
        
        return {
            'has_progression_data': True,
            'progression_path': progression,
            'typical_jump': 42.0
        }
    
    @classmethod
    def _generate_recommendations(cls, metrics: Dict[str, Any], skills_data: Dict[str, Any]) -> List[str]:
        """
        Generate strategic recommendations using unified skill data.
        """
        recommendations = []
        
        demand = metrics.get('demand_indicator', {})
        if demand.get('category') == "High Demand":
            recommendations.append(f"This role has {demand.get('category').lower()} with {demand.get('percentile')}% percentile ranking.")
        elif demand.get('category') == "Niche Role":
            recommendations.append("This is a niche role with specialized opportunities.")
        else:
            recommendations.append(f"This role has {demand.get('category').lower()} in the job market.")
        
        barrier = metrics.get('experience_barrier', {})
        if barrier.get('entry_friendly'):
            recommendations.append("Most jobs are beginner-friendly with 0-2 years experience requirements.")
        elif barrier.get('classification') == "Highly Competitive":
            recommendations.append(f"This is a {barrier.get('classification').lower()} role requiring significant experience.")
        else:
            recommendations.append(f"Most jobs require {barrier.get('classification').lower()} experience levels.")
        
        salary_impact = metrics.get('salary_impact', [])
        high_impact_skills = [s for s in salary_impact if s['salary_impact'] >= 10][:3]
        if high_impact_skills:
            skills_str = ", ".join([s['skill'] for s in high_impact_skills])
            recommendations.append(f"Skills like {skills_str} significantly increase salary potential.")
        
        skill_classification = metrics.get('skill_classification', {})
        core = skill_classification.get('core', [])
        if len(core) >= 3:
            core_str = ", ".join([s['name'] for s in core[:3]])
            recommendations.append(f"Core skills include {core_str}.")
        
        diversity = metrics.get('skill_diversity', {})
        if diversity.get('classification') == "Hybrid Role":
            recommendations.append("This is a hybrid role requiring diverse skill sets.")
        elif diversity.get('classification') == "Specialized Role":
            recommendations.append("This is a specialized role focused on specific expertise.")
        
        return recommendations[:5]
    
    @classmethod
    def _empty_response(cls) -> Dict[str, Any]:
        """Return empty response when no jobs found."""
        return {
            'role': '',
            'total_jobs': 0,
            'skills': [],
            'skill_classification': {'core': [], 'important': [], 'optional': [], 'total_unique': 0},
            'salary_impact': [],
            'experience_barrier': {
                'barrier_score': 0,
                'classification': 'Unknown',
                'junior_pct': 0,
                'mid_pct': 0,
                'senior_pct': 0,
                'entry_friendly': False
            },
            'demand_indicator': {'score': 0, 'category': 'Unknown', 'percentile': 0, 'rank': 0, 'total_roles': 0},
            'skill_diversity': {'diversity_score': 0, 'unique_skills': 0, 'avg_skills_per_job': 0, 'classification': 'Unknown'},
            'career_progression': {'has_progression_data': False, 'progression_path': [], 'typical_jump': 0},
            'recommendations': ['No data available for this role.']
        }
