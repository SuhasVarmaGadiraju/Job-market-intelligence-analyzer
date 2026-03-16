from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Max, Min
from django.http import JsonResponse

from django.shortcuts import render
from django.template.loader import render_to_string
from .models import Job, Role, SalaryData
from .services.role_intelligence_engine import RoleIntelligenceEngine
from .services.skill_gap_precompute import (
    warm_role_skill_index,
    get_role_classification,
    role_options as _precomputed_role_options,
)
from .services.salary_insights_precompute import get_salary_insights
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login, logout, authenticate
from django.shortcuts import redirect
import re
import hashlib
from django.core.cache import cache

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')

    else:
        form = UserCreationForm()

    return render(request, 'analyzer/register.html', {'form': form})

def user_login(request):
    login_error = False
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        login_error = True
    return render(request, 'analyzer/login.html', {'login_error': login_error})

def user_logout(request):
    logout(request)
    return redirect('home')
def home(request):
    return render(request, 'analyzer/home.html')

@login_required
def dashboard(request):
    total_jobs = Job.objects.count()
    total_roles = Role.objects.count()
    context = {
        'app_layout': True,
        'active_page': 'dashboard',
        'total_jobs': total_jobs,
        'total_roles': total_roles,
    }
    return render(request, 'analyzer/dashboard.html', context)

def role_intelligence(request):
    top_roles = (
        Job.objects.values("title")
        .annotate(count=Count("id"))
        .order_by("-count")[:15]
    )
    data = [{"title": r["title"], "count": r["count"]} for r in top_roles]
    return JsonResponse(data, safe=False)

def _role_options_cached():
    if not _precomputed_role_options():
        warm_role_skill_index()
    return _precomputed_role_options()

def _default_role_cached():
    key = "role_default:v1"
    cached = cache.get(key)
    if cached is not None:
        return cached
    top = (
        Job.objects.exclude(title__isnull=True)
        .exclude(title__exact="")
        .values("title")
        .annotate(count=Count("id"))
        .order_by("-count")
        .first()
    )
    role = top["title"] if top else ""
    cache.set(key, role, 60 * 10)
    return role

@login_required
def role_search(request):
    q = (request.GET.get("q") or "").strip()
    q_norm = q[:80]
    if len(q_norm) < 2:
        return JsonResponse({"results": []})
    key = f"role_search:v1:{q_norm.lower()}"
    cached = cache.get(key)
    if cached is not None:
        return JsonResponse({"results": cached})

    qs = Job.objects.exclude(title__isnull=True).exclude(title__exact="")
    if q_norm:
        qs = qs.filter(title__icontains=q_norm)

    roles = list(qs.values_list("title", flat=True).distinct().order_by("title"))
    results = [{"value": r, "text": r} for r in roles]
    cache.set(key, results, 60 * 5)
    return JsonResponse({"results": results})

@login_required
def api_search_roles(request):
    q = (request.GET.get("q") or "").strip()
    q_norm = q[:80]
    try:
        page = int(request.GET.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)

    page_size = 200
    start = (page - 1) * page_size
    end = start + page_size

    key = f"api_search_roles:v2:{q_norm.lower()}:{page}"
    cached = cache.get(key)
    if cached is not None:
        return JsonResponse(cached)

    qs = Job.objects.exclude(title__isnull=True).exclude(title__exact="")
    if q_norm:
        qs = qs.filter(title__icontains=q_norm)

    titles = list(qs.values_list("title", flat=True).distinct().order_by("title")[start : end + 1])
    more = len(titles) > page_size
    titles = titles[:page_size]

    payload = {
        "results": [{"id": r, "text": r} for r in titles],
        "pagination": {"more": more},
    }
    cache.set(key, payload, 60 * 5)
    return JsonResponse(payload)

def _global_role_trend_cached():
    key = "role_trend_global:v1"
    cached = cache.get(key)
    if cached is not None:
        return cached

    top_roles = (
        Job.objects.exclude(title__isnull=True)
        .exclude(title__exact="")
        .values("title")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    trend_labels = [r["title"] for r in top_roles]
    trend_values = [r["count"] for r in top_roles]
    if not trend_labels:
        trend_labels = ["No data"]
        trend_values = [0]

    data = {"labels": trend_labels, "values": trend_values}
    cache.set(key, data, 60 * 10)
    return data

_SKILL_SPLIT_RE = re.compile(r"[\n\r,;|/]+")

def _compute_role_analytics_cached(selected_role):
    key = f"role_analytics:v4:{selected_role}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    def parse_experience_years(text):
        if not text:
            return None
        t = text.strip().lower()
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

    role_qs = Job.objects.filter(title=selected_role)
    total_jobs_for_role = role_qs.count()

    salary_qs = role_qs.exclude(final_salary__isnull=True).filter(final_salary__gt=0)
    salary_aggs = salary_qs.aggregate(
        min_salary=Min("final_salary"),
        avg_salary=Avg("final_salary"),
        max_salary=Max("final_salary"),
    )

    # USE UNIFIED SKILL AGGREGATION from RoleIntelligenceEngine
    career_data = RoleIntelligenceEngine.analyze_role(selected_role)
    unified_skills = career_data.get('skills', [])  # Top 10 skills from unified aggregation

    # Build chart data from unified skills
    skills_labels = [s['name'] for s in unified_skills]
    skills_values = [s['frequency'] for s in unified_skills]

    # Get top skill from unified data
    top_skill = "—"
    if unified_skills:
        top_skill = unified_skills[0]['name']

    # Experience calculation (unchanged)
    exp_counts = {"0–2 years": 0, "2–5 years": 0, "5+ years": 0}
    exp_raw_counts = {}

    for exp_text in role_qs.values_list("experience", flat=True).iterator(chunk_size=2000):
        exp_raw = (exp_text or "").strip()
        if exp_raw:
            exp_raw_counts[exp_raw] = exp_raw_counts.get(exp_raw, 0) + 1
        years = parse_experience_years(exp_raw)
        if years is None:
            continue
        if years <= 2:
            exp_counts["0–2 years"] += 1
        elif years <= 5:
            exp_counts["2–5 years"] += 1
        else:
            exp_counts["5+ years"] += 1

    most_common_experience = "—"
    if exp_raw_counts:
        most_common_experience = max(exp_raw_counts.items(), key=lambda kv: kv[1])[0]

    exp_labels = list(exp_counts.keys())
    exp_values = [exp_counts[k] for k in exp_labels]
    if sum(exp_values) == 0:
        exp_labels = ["No data"]
        exp_values = [1]

    payload = {
        "selected_role": selected_role,
        "summary": {
            "total_jobs_for_role": total_jobs_for_role,
            "avg_salary": salary_aggs.get("avg_salary"),
            "min_salary": salary_aggs.get("min_salary"),
            "max_salary": salary_aggs.get("max_salary"),
            "top_skill": top_skill,
            "most_common_experience": most_common_experience,
        },
        "skills": {"labels": skills_labels, "values": skills_values},
        "skills_top_n": len(skills_labels),
        "experience": {"labels": exp_labels, "values": exp_values},
    }

    cache.set(key, payload, 60 * 10)
    return payload

@login_required
def role_analytics_data(request):
    selected_role = (request.GET.get("role") or "").strip()
    if selected_role and not Job.objects.filter(title=selected_role).exists():
        selected_role = ""
    if not selected_role:
        selected_role = _default_role_cached()

    if not selected_role:
        return JsonResponse(
            {
                "selected_role": "",
                "summary": {
                    "total_jobs_for_role": 0,
                    "avg_salary": None,
                    "min_salary": None,
                    "max_salary": None,
                    "top_skill": "—",
                    "most_common_experience": "—",
                },
                "skills": {"labels": ["No data"], "values": [0]},
                "skills_top_n": 0,
                "experience": {"labels": ["No data"], "values": [1]},
                "trend": _global_role_trend_cached(),
            }
        )

    payload = _compute_role_analytics_cached(selected_role)
    payload = dict(payload)
    payload["trend"] = _global_role_trend_cached()
    return JsonResponse(payload)

@login_required
def role(request):
    selected_role = (request.GET.get("role") or "").strip()
    if selected_role and not Job.objects.filter(title=selected_role).exists():
        selected_role = ""
    if not selected_role:
        selected_role = _default_role_cached()

    role_options = _role_options_cached()

    initial = None
    if selected_role:
        initial = _compute_role_analytics_cached(selected_role)
    else:
        initial = {
            "selected_role": "",
            "summary": {
                "total_jobs_for_role": 0,
                "avg_salary": None,
                "min_salary": None,
                "max_salary": None,
                "top_skill": "—",
                "most_common_experience": "—",
            },
            "skills": {"labels": ["No data"], "values": [0]},
            "skills_top_n": 0,
            "experience": {"labels": ["No data"], "values": [1]},
        }

    initial = dict(initial)
    initial["trend"] = _global_role_trend_cached()
    
    # Add career intelligence from the new engine
    if selected_role:
        career_analytics = RoleIntelligenceEngine.analyze_role(selected_role)
        initial["career_intelligence"] = career_analytics

    return render(
        request,
        'analyzer/role.html',
        {
            'app_layout': True,
            'active_page': 'role',
            'role_options': role_options,
            'selected_role': selected_role,
            'initial_data': initial,
        },
    )

@login_required
def skill_gap(request):
    """Skill Gap Analysis page with form and results."""
    context = {
        'app_layout': True,
        'active_page': 'skill_gap',
    }
    
    # GET method for URL sharing and browser navigation
    target_role = request.GET.get('role', '').strip()
    user_skills_raw = request.GET.get('skills', '').strip()
    experience_level = request.GET.get('experience', '').strip()
    
    # Always include selected values in context to preserve form state
    context['target_role'] = target_role
    context['user_skills_raw'] = user_skills_raw
    context['experience_level'] = experience_level
    
    # Load cached unique roles for Tom Select
    context['role_options'] = _role_options_cached()
    
    if target_role and user_skills_raw:
        analysis = _analyze_skill_gap(target_role, user_skills_raw, experience_level)
        context['analysis'] = analysis
    
    return render(request, 'analyzer/skill_gap.html', context)

@login_required
def skill_gap_analyze(request):
    target_role = (request.GET.get('role') or '').strip()
    user_skills_raw = (request.GET.get('skills') or '').strip()
    experience_level = (request.GET.get('experience') or '').strip()

    analysis = None
    if target_role and user_skills_raw:
        analysis = _analyze_skill_gap(target_role, user_skills_raw, experience_level)
    elif target_role or user_skills_raw:
        analysis = {'error': 'Please select a target role and enter your skills.'}

    html = render_to_string(
        'analyzer/partials/skill_gap_results.html',
        {'analysis': analysis},
        request=request,
    )
    return JsonResponse({'html': html})

def _normalize_skill_input(skills_str: str) -> set:
    """Normalize user input skills to a set of lowercase strings."""
    if not skills_str:
        return set()
    skills = re.split(r'[,;/|•\n]+', skills_str)
    return {s.strip().lower() for s in skills if s.strip()}

def _analyze_skill_gap(target_role: str, user_skills_raw: str, experience_level: str) -> dict:
    """
    Perform skill gap analysis using precomputed role skill classification.
    Cached for 1 hour per (role + skills + experience) combination.
    """
    skills_hash = hashlib.md5(user_skills_raw.lower().encode()).hexdigest()[:12]
    cache_key = f"skill_gap_analysis:{target_role.lower().replace(' ', '_')}:{skills_hash}:{experience_level}"
    
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result
    
    # Use precomputed role classification (fast - no DB queries for skills)
    role_data = get_role_classification(target_role)
    
    if role_data is None or role_data.total_jobs == 0:
        return {'error': 'No data available for this role'}
    
    # Normalize user skills
    user_skills = _normalize_skill_input(user_skills_raw)
    
    # Get precomputed classified skills
    core_skills = [s.lower() for s in role_data.core]
    important_skills = [s.lower() for s in role_data.important]
    optional_skills = [s.lower() for s in role_data.optional]
    classification_note = role_data.note
    
    # Categorize user skills against precomputed lists
    matching_core = []
    missing_core = []
    matching_important = []
    missing_important = []
    matching_optional = []
    
    for skill in core_skills:
        if any(user_skill in skill or skill in user_skill for user_skill in user_skills):
            matching_core.append(skill.title())
        else:
            missing_core.append(skill.title())
    
    for skill in important_skills:
        if any(user_skill in skill or skill in user_skill for user_skill in user_skills):
            matching_important.append(skill.title())
        else:
            missing_important.append(skill.title())
    
    for skill in optional_skills:
        if any(user_skill in skill or skill in user_skill for user_skill in user_skills):
            matching_optional.append(skill.title())
    
    # Calculate gap score
    total_core = len(core_skills)
    missing_core_count = len(missing_core)
    if total_core <= 0:
        return {'error': 'No core skills available for this role.'}

    gap_score = (missing_core_count / total_core * 100)

    # Determine readiness (per spec)
    if gap_score <= 30:
        readiness = "Job Ready"
        readiness_class = "ready"
    elif gap_score <= 60:
        readiness = "Moderate Gap"
        readiness_class = "moderate"
    else:
        readiness = "High Gap"
        readiness_class = "high"
    
    # Salary impact - use RoleIntelligenceEngine (cached internally)
    salary_data = RoleIntelligenceEngine.analyze_role(target_role)
    salary_impacts = salary_data.get('salary_impact', [])
    missing_skill_salary_boost = []
    
    for impact in salary_impacts:
        skill_name = impact['skill'].lower()
        if skill_name in [s.lower() for s in missing_core]:
            missing_skill_salary_boost.append({
                'skill': impact['skill'],
                'boost_percent': impact['salary_impact'],
                'avg_salary_with': impact['avg_salary_with'],
            })
    
    missing_skill_salary_boost = sorted(
        missing_skill_salary_boost,
        key=lambda x: x['boost_percent'],
        reverse=True
    )[:5]
    
    # Generate insight
    insight = _generate_gap_insight(
        readiness, gap_score, len(matching_core),
        missing_core_count, total_core, missing_skill_salary_boost
    )
    
    has_gap = missing_core_count > 0

    result = {
        'target_role': target_role,
        'experience_level': experience_level,
        'total_jobs_analyzed': role_data.total_jobs,
        'gap_score': round(gap_score, 1),
        'readiness': readiness,
        'readiness_class': readiness_class,
        'has_gap': has_gap,
        'matching_core': matching_core,
        'missing_core': missing_core,
        'matching_important': matching_important,
        'missing_important': missing_important[:10],
        'matching_optional': matching_optional,
        'total_core': total_core,
        'total_important': len(important_skills),
        'salary_boost_skills': missing_skill_salary_boost,
        'insight': insight,
        'classification_note': classification_note,
        'has_important_skills': len(important_skills) > 0,
    }
    
    cache.set(cache_key, result, 60 * 60)
    return result

def _generate_gap_insight(readiness, gap_score, matching_count, missing_count, total_core, salary_boosts):
    """Generate auto-insight message based on gap analysis."""
    if readiness == "Job Ready":
        base = f"Excellent! You have {matching_count} of {total_core} core skills. You're well-positioned for this role."
    elif readiness == "Moderate Gap":
        base = f"You have {matching_count} of {total_core} core skills with a {round(gap_score)}% gap. Focus on the missing core skills below."
    else:
        base = f"Significant gap detected ({round(gap_score)}%). You have only {matching_count} of {total_core} core skills. Consider intensive upskilling."
    
    if salary_boosts:
        top_skill = salary_boosts[0]['skill']
        boost = salary_boosts[0]['boost_percent']
        base += f" Learning {top_skill} could boost salary by {boost}%."
    
    return base

@login_required
def salary(request):
    selected_role = (request.GET.get("role") or "").strip()
    if selected_role and not Job.objects.filter(title=selected_role).exists():
        selected_role = ""
    if not selected_role:
        selected_role = _default_role_cached()

    initial = None
    if selected_role:
        insights = get_salary_insights(selected_role)
        if insights:
            initial = {
                "selected_role": selected_role,
                "summary": {
                    "min_salary": insights.min_salary,
                    "avg_salary": insights.avg_salary,
                    "max_salary": insights.max_salary,
                    "median_salary": insights.median_salary,
                    "total_jobs_with_salary": insights.total_jobs_with_salary,
                },
                "salary_by_experience": insights.salary_by_experience,
                "top_cities": insights.top_cities,
                "skills_that_increase_salary": insights.skills_that_increase_salary,
            }

    if initial is None:
        initial = {
            "selected_role": selected_role or "",
            "summary": {
                "min_salary": None,
                "avg_salary": None,
                "max_salary": None,
                "median_salary": None,
                "total_jobs_with_salary": 0,
            },
            "salary_by_experience": [],
            "top_cities": [],
            "skills_that_increase_salary": [],
        }

    return render(
        request,
        'analyzer/salary.html',
        {
            'app_layout': True,
            'active_page': 'salary',
            'selected_role': selected_role,
            'initial_data': initial,
        },
    )

@login_required
def salary_insights_data(request):
    selected_role = (request.GET.get("role") or "").strip()
    if selected_role and not Job.objects.filter(title=selected_role).exists():
        selected_role = ""
    if not selected_role:
        selected_role = _default_role_cached()

    payload = {
        "selected_role": selected_role or "",
        "summary": {
            "min_salary": None,
            "avg_salary": None,
            "max_salary": None,
            "median_salary": None,
            "total_jobs_with_salary": 0,
        },
        "salary_by_experience": [],
        "top_cities": [],
        "skills_that_increase_salary": [],
    }

    if selected_role:
        insights = get_salary_insights(selected_role)
        if insights:
            payload = {
                "selected_role": selected_role,
                "summary": {
                    "min_salary": insights.min_salary,
                    "avg_salary": insights.avg_salary,
                    "max_salary": insights.max_salary,
                    "median_salary": insights.median_salary,
                    "total_jobs_with_salary": insights.total_jobs_with_salary,
                },
                "salary_by_experience": insights.salary_by_experience,
                "top_cities": insights.top_cities,
                "skills_that_increase_salary": insights.skills_that_increase_salary,
            }

    return JsonResponse(payload)

@login_required
def trend_tracking(request):
    return render(request, 'analyzer/trend_tracking.html', {'app_layout': True, 'active_page': 'trend_tracking'})

@login_required
def profile(request):
    return render(
        request,
        'analyzer/profile.html',
        {
            'app_layout': True,
            'active_page': 'profile',
        },
    )

@login_required
def settings(request):
    if request.method == 'POST':
        notify = request.POST.get('notifications') == 'on'
        request.session['notifications_enabled'] = notify
        return redirect('settings')

    notifications_enabled = bool(request.session.get('notifications_enabled', False))
    return render(
        request,
        'analyzer/settings.html',
        {
            'app_layout': True,
            'active_page': 'settings',
            'notifications_enabled': notifications_enabled,
        },
    )

@login_required
def activity(request):
    request.session['activity_visit_count'] = int(request.session.get('activity_visit_count', 0)) + 1
    request.session.modified = True

    total_jobs = Job.objects.count()
    return render(
        request,
        'analyzer/activity.html',
        {
            'app_layout': True,
            'active_page': 'activity',
            'total_jobs': total_jobs,
            'last_login': request.user.last_login,
            'visit_count': request.session.get('activity_visit_count', 1),
        },
    )