"""
Role Intelligence Engine - Career Analytics Service

Transforms raw job data into strategic career intelligence.
Provides insights for skills, salary impact, competition, and recommendations.
"""

import re
from typing import Dict, List, Tuple, Any, Set
from django.db.models import Avg, Count, Q
from django.core.cache import cache
from analyzer.models import Job


# Cache TTL in seconds (5 minutes)
CACHE_TTL = 60 * 5


def _normalize_skills(skills_str: str) -> List[str]:
    """Normalize and split skills string into individual skills."""
    if not skills_str:
        return []
    # Split by common delimiters and normalize
    skills = re.split(r'[,;/|•]', skills_str)
    return [s.strip().lower() for s in skills if s.strip()]


def _parse_experience(exp_str: str) -> float:
    """Parse experience string to extract numeric years."""
    if not exp_str:
        return 0
    
    # Look for patterns like "3-5 years", "5+ years", "2 years"
    match = re.search(r'(\d+)[-–]?(?:\d+)?\s*(?:\+)?\s*(?:years?|yrs?)', str(exp_str).lower())
    if match:
        return float(match.group(1))
    
    # Try simple numeric extraction
    match = re.search(r'(\d+)', str(exp_str))
    if match:
        return float(match.group(1))
    
    return 0


class RoleIntelligenceEngine:
    """
    Core engine for calculating career intelligence metrics.
    
    Provides:
    - Skill importance classification
    - Salary impact analysis
    - Experience barrier scoring
    - Demand indicators
    - Diversity metrics
    - Strategic recommendations
    
    All skill calculations use a SINGLE unified aggregation to ensure
    consistency across Skill Demand Chart, Skill Classification, 
    Salary Impact, and Career Insights.
    """
    
    @classmethod
    def analyze_role(cls, role_title: str) -> Dict[str, Any]:
        """
        Main entry point. Returns comprehensive career intelligence for a role.
        
        Args:
            role_title: The job role/title to analyze
            
        Returns:
            Dict containing all career analytics
        """
        cache_key = f"role_intelligence:{role_title.lower().replace(' ', '_')}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Get jobs for this role
        jobs = Job.objects.filter(title__iexact=role_title)
        total_jobs = jobs.count()
        
        if total_jobs == 0:
            return cls._empty_response()
        
        # SINGLE UNIFIED SKILL AGGREGATION
        # This ensures all features use the same skill data
        skills_data = cls._aggregate_skills(jobs, total_jobs)
        
        # Calculate all metrics using unified skill data
        result = {
            'role': role_title,
            'total_jobs': total_jobs,
            # Unified skill data for chart and classification
            'skills': skills_data['all_skills'],  # Top 10 for chart
            'skill_classification': cls._classify_skills_from_data(skills_data, total_jobs),
            'salary_impact': cls._calculate_salary_impact_with_data(jobs, skills_data, total_jobs),
            'experience_barrier': cls._calculate_experience_barrier(jobs, total_jobs),
            'demand_indicator': cls._calculate_demand_indicator(role_title, total_jobs),
            'skill_diversity': cls._calculate_skill_diversity_from_data(skills_data, total_jobs),
            'career_progression': cls._analyze_career_progression(role_title),
            'recommendations': [],
        }
        
        # Generate recommendations based on all metrics
        result['recommendations'] = cls._generate_recommendations(result, skills_data)
        
        cache.set(cache_key, result, CACHE_TTL)
        return result
    
    @classmethod
    def _aggregate_skills(cls, jobs, total_jobs: int) -> Dict[str, Any]:
        """
        SINGLE UNIFIED SKILL AGGREGATION FUNCTION.
        
        Extracts skills once, normalizes, removes duplicates per job,
        and computes frequency and percentage for each skill.
        
        Returns:
            Dict containing:
            - skill_stats: {skill_name: {frequency, percentage}}
            - job_skills_map: {job_id: [skills]}
            - all_skills: [{name, frequency, percentage}] (sorted for chart)
            - unique_count: total unique skills
        """
        skill_stats = {}  # {skill: {'frequency': int, 'percentage': float}}
        job_skills_map = {}  # {job_id: [skills]}
        
        for job in jobs:
            # Normalize and deduplicate skills for this job
            raw_skills = _normalize_skills(job.skills)
            unique_job_skills = list(set(raw_skills))  # Remove duplicates per job
            
            job_skills_map[job.id] = unique_job_skills
            
            # Count frequency (each skill counted once per job)
            for skill in unique_job_skills:
                if skill not in skill_stats:
                    skill_stats[skill] = {'frequency': 0, 'percentage': 0.0}
                skill_stats[skill]['frequency'] += 1
        
        # Calculate percentages and prepare chart data
        all_skills_list = []
        for skill, stats in skill_stats.items():
            percentage = (stats['frequency'] / total_jobs) * 100
            stats['percentage'] = round(percentage, 1)
            all_skills_list.append({
                'name': skill.title(),
                'frequency': stats['frequency'],
                'percentage': round(percentage, 1)
            })
        
        # Sort by frequency descending (for chart display)
        all_skills_list.sort(key=lambda x: x['frequency'], reverse=True)
        
        return {
            'skill_stats': skill_stats,  # {skill: {frequency, percentage}}
            'job_skills_map': job_skills_map,  # {job_id: [skills]}
            'all_skills': all_skills_list[:10],  # Top 10 for chart
            'unique_count': len(skill_stats)
        }
    
    @classmethod
    def _classify_skills_from_data(cls, skills_data: Dict[str, Any], total_jobs: int) -> Dict[str, Any]:
        """
        Classify skills by importance using unified skill data.
        
        Uses percentage thresholds:
        - Core: >= 70%
        - Important: 30-70%
        - Optional: < 30%
        
        Returns:
            Dict with core, important, and optional skills
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
        
        # Sort by importance score (percentage)
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
    def _calculate_salary_impact_with_data(cls, jobs, skills_data: Dict[str, Any], total_jobs: int) -> List[Dict[str, Any]]:
        """
        Calculate salary impact using unified skill data.
        
        Returns:
            List of skills with salary impact percentages
        """
        skill_stats = skills_data['skill_stats']
        job_skills_map = skills_data['job_skills_map']
        
        # Calculate average salary for all jobs
        avg_salary_all = jobs.filter(final_salary__isnull=False).aggregate(
            avg=Avg('final_salary')
        )['avg'] or 0
        
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
            
            if len(jobs_with_skill) < 3:  # Need minimum sample size
                continue
            
            avg_with = sum(jobs_with_skill) / len(jobs_with_skill)
            avg_without = sum(jobs_without_skill) / len(jobs_without_skill) if jobs_without_skill else avg_salary_all
            
            # Calculate percentage difference
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
        
        # Sort by impact and return top 10
        salary_impacts = sorted(salary_impacts, key=lambda x: x['salary_impact'], reverse=True)
        return salary_impacts[:10]
    
    @classmethod
    def _calculate_skill_diversity_from_data(cls, skills_data: Dict[str, Any], total_jobs: int) -> Dict[str, Any]:
        """
        Calculate skill diversity using unified skill data.
        
        Returns:
            Dict with diversity metrics
        """
        unique_count = skills_data['unique_count']
        job_skills_map = skills_data['job_skills_map']
        
        # Calculate total skill mentions (for avg per job)
        total_skill_mentions = sum(len(skills) for skills in job_skills_map.values())
        
        # Diversity score: unique skills per job
        diversity_score = unique_count / total_jobs if total_jobs > 0 else 0
        
        # Average skills per job
        avg_skills_per_job = total_skill_mentions / total_jobs if total_jobs > 0 else 0
        
        # Classification
        if diversity_score <= 2:
            classification = "Specialized Role"
        elif diversity_score <= 5:
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
        
        Returns:
            Dict with barrier score and classification
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
        
        # Calculate barrier score (% of jobs requiring 5+ years)
        high_exp_jobs = exp_counts['senior']
        barrier_score = (high_exp_jobs / total_jobs) * 100 if total_jobs > 0 else 0
        
        # Classify the role
        if barrier_score >= 50:
            classification = "Highly Competitive"
        elif barrier_score >= 20:
            classification = "Mid-Level"
        else:
            classification = "Beginner Friendly"
        
        return {
            'barrier_score': round(barrier_score, 1),
            'classification': classification,
            'junior_pct': round((exp_counts['junior'] / total_jobs) * 100, 1),
            'mid_pct': round((exp_counts['mid'] / total_jobs) * 100, 1),
            'senior_pct': round((exp_counts['senior'] / total_jobs) * 100, 1),
            'entry_friendly': exp_counts['junior'] > (exp_counts['senior'] * 1.5)
        }
    
    @classmethod
    def _calculate_demand_indicator(cls, role_title: str, role_jobs: int) -> Dict[str, Any]:
        """
        Calculate demand strength indicator.
        
        Returns:
            Dict with demand score and category
        """
        total_dataset_jobs = Job.objects.count()
        
        if total_dataset_jobs == 0:
            return {'score': 0, 'category': 'Unknown', 'percentile': 0}
        
        demand_score = (role_jobs / total_dataset_jobs) * 100
        
        # Get percentile rank
        all_roles_count = Job.objects.values('title').annotate(
            count=Count('id')
        ).order_by('-count')
        
        higher_roles = sum(1 for r in all_roles_count if r['count'] > role_jobs)
        total_roles = len(all_roles_count)
        percentile = ((total_roles - higher_roles) / total_roles) * 100 if total_roles > 0 else 50
        
        # Categorize
        if demand_score >= 2.0 or percentile >= 80:
            category = "High Demand"
        elif demand_score >= 0.5 or percentile >= 50:
            category = "Moderate Demand"
        else:
            category = "Niche Role"
        
        return {
            'score': round(demand_score, 2),
            'category': category,
            'percentile': round(percentile, 1),
            'rank': higher_roles + 1,
            'total_roles': total_roles
        }
    
    @classmethod
    def _analyze_career_progression(cls, role_title: str) -> Dict[str, Any]:
        """
        Analyze career progression if seniority data is available.
        
        Returns:
            Dict with progression insights
        """
        # Look for related roles with seniority indicators
        base_title = role_title.lower().replace('senior ', '').replace('junior ', '').replace('lead ', '')
        
        levels = {
            'junior': Job.objects.filter(
                Q(title__icontains=f"junior {base_title}") | 
                Q(title__icontains=f"jr {base_title}")
            ).aggregate(avg_salary=Avg('final_salary'), count=Count('id')),
            'mid': Job.objects.filter(
                title__icontains=base_title
            ).exclude(
                Q(title__icontains='senior') | 
                Q(title__icontains='junior') | 
                Q(title__icontains='lead')
            ).aggregate(avg_salary=Avg('final_salary'), count=Count('id')),
            'senior': Job.objects.filter(
                Q(title__icontains=f"senior {base_title}") | 
                Q(title__icontains=f"sr {base_title}")
            ).aggregate(avg_salary=Avg('final_salary'), count=Count('id')),
            'lead': Job.objects.filter(
                Q(title__icontains=f"lead {base_title}") | 
                Q(title__icontains=f"principal {base_title}") |
                Q(title__icontains=f"staff {base_title}")
            ).aggregate(avg_salary=Avg('final_salary'), count=Count('id'))
        }
        
        progression = []
        prev_salary = None
        
        for level, data in levels.items():
            if data['count'] and data['count'] > 0:
                salary = data['avg_salary'] or 0
                jump = 0
                if prev_salary and prev_salary > 0:
                    jump = ((salary - prev_salary) / prev_salary) * 100
                
                progression.append({
                    'level': level.title(),
                    'avg_salary': round(salary, 0) if salary else None,
                    'salary_jump_pct': round(jump, 1) if jump else None,
                    'job_count': data['count']
                })
                prev_salary = salary
        
        return {
            'has_progression_data': len(progression) > 1,
            'progression_path': progression,
            'typical_jump': round(sum([p['salary_jump_pct'] for p in progression if p['salary_jump_pct']]) / max(1, len([p for p in progression if p['salary_jump_pct']])), 1)
        }
    
    @classmethod
    def _generate_recommendations(cls, metrics: Dict[str, Any], skills_data: Dict[str, Any]) -> List[str]:
        """
        Generate strategic recommendations using unified skill data.
        
        Returns:
            List of insight strings
        """
        recommendations = []
        
        # Demand insight
        demand = metrics.get('demand_indicator', {})
        if demand.get('category') == "High Demand":
            recommendations.append(f"This role has {demand.get('category').lower()} with {demand.get('percentile')}% percentile ranking.")
        elif demand.get('category') == "Niche Role":
            recommendations.append("This is a niche role with specialized opportunities.")
        else:
            recommendations.append(f"This role has {demand.get('category').lower()} in the job market.")
        
        # Experience barrier insight
        barrier = metrics.get('experience_barrier', {})
        if barrier.get('entry_friendly'):
            recommendations.append("Most jobs are beginner-friendly with 0-2 years experience requirements.")
        elif barrier.get('classification') == "Highly Competitive":
            recommendations.append(f"This is a {barrier.get('classification').lower()} role requiring significant experience.")
        else:
            recommendations.append(f"Most jobs require {barrier.get('classification').lower()} experience levels.")
        
        # Salary impact insight
        salary_impact = metrics.get('salary_impact', [])
        high_impact_skills = [s for s in salary_impact if s['salary_impact'] >= 10][:3]
        if high_impact_skills:
            skills_str = ", ".join([s['skill'] for s in high_impact_skills])
            recommendations.append(f"Skills like {skills_str} significantly increase salary potential.")
        
        # Core skills insight using unified data
        skill_classification = metrics.get('skill_classification', {})
        core = skill_classification.get('core', [])
        if len(core) >= 3:
            core_str = ", ".join([s['name'] for s in core[:3]])
            recommendations.append(f"Core skills include {core_str}.")
        
        # Diversity insight
        diversity = metrics.get('skill_diversity', {})
        if diversity.get('classification') == "Hybrid Role":
            recommendations.append("This is a hybrid role requiring diverse skill sets.")
        elif diversity.get('classification') == "Specialized Role":
            recommendations.append("This is a specialized role focused on specific expertise.")
        
        # Competition insight
        if barrier.get('barrier_score', 0) > 50 and demand.get('score', 0) > 2:
            recommendations.append("High demand but competitive - focus on building core skills first.")
        elif demand.get('score', 0) > 2 and barrier.get('barrier_score', 0) < 30:
            recommendations.append("Good entry opportunity with strong market demand.")
        
        return recommendations[:5]  # Return top 5 recommendations
    
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
