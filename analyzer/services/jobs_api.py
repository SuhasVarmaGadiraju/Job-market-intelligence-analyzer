import os
import requests
import logging
import re
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour minimum cache

POPULAR_SKILLS = [
    "python", "javascript", "java", "c++", "c#", "ruby", "php", "go", "golang", "rust", "swift", "kotlin", "typescript",
    "html", "css", "react", "angular", "vue", "node.js", "django", "flask", "fastapi", "spring", "asp.net", "laravel",
    "sql", "mysql", "postgresql", "mongodb", "redis", "cassandra", "elasticsearch", "sqlite", "oracle",
    "aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "git", "github", "gitlab", "ansible", "terraform",
    "machine learning", "deep learning", "nlp", "computer vision", "tensorflow", "pytorch", "keras", "scikit-learn",
    "data science", "data analysis", "pandas", "numpy", "matplotlib", "seaborn", "tableau", "power bi",
    "agile", "scrum", "project management", "product management", "system design", "microservices", "graphql", "rest api",
    "linux", "unix", "bash", "shell scripting", "devops", "ci/cd", "qa", "testing", "selenium", "cypress", "mocha", "jest"
]

def extract_skills_from_text(text: str) -> str:
    """Extract known popular skills from job description text."""
    if not text:
        return ""
    text_lower = text.lower()
    found_skills = []
    for skill in POPULAR_SKILLS:
        # Match as whole word to avoid sub-string matching issues (e.g. 'go' in 'good')
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text_lower):
            found_skills.append(skill.title())
    return ", ".join(found_skills)

def fetch_live_jobs_from_api(query: str, num_pages: int = 2) -> list:
    """
    Fetch jobs dynamically from JSearch API.
    Accepts role/query parameters, handles errors, caches raw results, and returns clean structured JSON.
    """
    if not query:
        return []

    cache_key = f"jsearch_raw_jobs:{query.lower().strip().replace(' ', '_')}"
    cached_jobs = cache.get(cache_key)
    if cached_jobs is not None:
        return cached_jobs

    api_key = getattr(settings, 'RAPIDAPI_KEY', None)
    if not api_key or api_key == "your_jsearch_rapidapi_key_here" or api_key == "your_key_here":
        logger.warning("RAPIDAPI_KEY is not configured or is a placeholder. Returning fallback mock data.")
        mock_jobs = get_mock_jobs_for_role(query)
        cache.set(cache_key, mock_jobs, CACHE_TTL)
        return mock_jobs

    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    
    params = {
        "query": f"{query} in India",
        "num_pages": num_pages,
        "page": 1
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 429:
            logger.error("JSearch API rate limit exceeded (429). Returning mock/cached data.")
            return get_mock_jobs_for_role(query)
        
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "OK" and "data" in data:
            raw_listings = data["data"]
            structured_jobs = []
            
            for index, job in enumerate(raw_listings):
                job_id = job.get("job_id", f"live_{query}_{index}")
                title = job.get("job_title", query)
                company = job.get("employer_name", "Unknown Company")
                
                # Combine city, state, country for location
                city = job.get("job_city")
                state = job.get("job_state")
                country = job.get("job_country")
                loc_parts = [p for p in [city, state, country] if p]
                location = ", ".join(loc_parts) if loc_parts else "India"
                
                # Parse Experience
                req_exp = job.get("job_required_experience", {})
                months = req_exp.get("required_experience_in_months")
                if months:
                    years = int(months) // 12
                    exp_str = f"{years}-{years+2} years" if years > 0 else "0-2 years"
                elif req_exp.get("no_experience_required"):
                    exp_str = "0-2 years"
                else:
                    desc = job.get("job_description", "")
                    match = re.search(r'(\d+)\s*\+?\s*years?', desc, re.IGNORECASE)
                    if match:
                        y = int(match.group(1))
                        exp_str = f"{y}-{y+2} years"
                    else:
                        exp_str = "2-5 years"
                
                # Parse Salary
                min_sal = job.get("job_min_salary")
                max_sal = job.get("job_max_salary")
                currency = job.get("job_salary_currency", "INR")
                period = job.get("job_salary_period", "YEAR")
                
                final_salary = None
                if min_sal and max_sal:
                    avg_sal = (float(min_sal) + float(max_sal)) / 2.0
                    final_salary = convert_salary_to_annual_inr(avg_sal, currency, period)
                elif min_sal:
                    final_salary = convert_salary_to_annual_inr(float(min_sal), currency, period)
                elif max_sal:
                    final_salary = convert_salary_to_annual_inr(float(max_sal), currency, period)
                else:
                    final_salary = estimate_salary_for_role(query, exp_str)
                
                # Extract skills from highlights/qualifications and job description
                highlights = job.get("job_highlights", {})
                quals = highlights.get("Qualifications", [])
                qual_text = " ".join(quals) if quals else ""
                desc_text = job.get("job_description", "")
                full_text = f"{title} {qual_text} {desc_text}"
                
                skills_str = extract_skills_from_text(full_text)
                if not skills_str:
                    skills_str = "Python, SQL, AWS"
                
                structured_jobs.append({
                    "id": job_id,
                    "job_id": job_id,
                    "title": title,
                    "company_name": company,
                    "location": location,
                    "experience": exp_str,
                    "final_salary": final_salary,
                    "skills": skills_str,
                    "description": desc_text[:500]
                })
            
            cache.set(cache_key, structured_jobs, CACHE_TTL)
            return structured_jobs
        
        return get_mock_jobs_for_role(query)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from JSearch API: {e}. Falling back to mock data.")
        return get_mock_jobs_for_role(query)

def convert_salary_to_annual_inr(salary: float, currency: str, period: str) -> float:
    """Helper to convert hourly/monthly and USD/EUR salaries to annual INR."""
    annual_sal = salary
    if period == "HOUR":
        annual_sal = salary * 2000
    elif period == "MONTH":
        annual_sal = salary * 12
    elif period == "WEEK":
        annual_sal = salary * 52
        
    inr_salary = annual_sal
    curr_upper = currency.upper()
    if curr_upper == "USD":
        inr_salary = annual_sal * 83.0
    elif curr_upper == "EUR":
        inr_salary = annual_sal * 90.0
    elif curr_upper == "GBP":
        inr_salary = annual_sal * 105.0
    elif curr_upper == "CAD":
        inr_salary = annual_sal * 61.0
        
    return round(inr_salary, 2)

def estimate_salary_for_role(role: str, experience: str) -> float:
    """Generate a realistic estimated INR salary based on role and experience."""
    role_lower = role.lower()
    base_sal = 600000.0  # Default base salary in INR (6 LPA)
    
    if "software" in role_lower or "developer" in role_lower or "engineer" in role_lower:
        base_sal = 800000.0
    if "data scientist" in role_lower or "machine learning" in role_lower or "ai" in role_lower:
        base_sal = 1000000.0
    if "manager" in role_lower or "lead" in role_lower:
        base_sal = 1500000.0
    if "designer" in role_lower or "ux" in role_lower:
        base_sal = 700000.0
        
    exp_lower = experience.lower()
    multiplier = 1.0
    if "5+" in exp_lower or "senior" in role_lower or "lead" in role_lower:
        multiplier = 2.2
    elif "2-5" in exp_lower or "mid" in exp_lower:
        multiplier = 1.5
    elif "0-2" in exp_lower or "junior" in role_lower:
        multiplier = 0.8
        
    return round(base_sal * multiplier, 2)

def get_mock_jobs_for_role(role: str) -> list:
    """Fallback generator for mock jobs in case API limits are hit or key is missing."""
    import random
    
    mock_companies = ["TCS", "Infosys", "Wipro", "Cognizant", "HCLTech", "Accenture", "Google", "Microsoft", "Amazon", "Flipkart"]
    mock_cities = ["Bangalore", "Hyderabad", "Mumbai", "Pune", "Chennai", "Delhi NCR", "Noida", "Gurugram"]
    
    role_skills_map = {
        "software engineer": ["Python", "Java", "JavaScript", "SQL", "Git", "Docker", "Kubernetes", "AWS", "HTML", "CSS", "TypeScript"],
        "data scientist": ["Python", "SQL", "Machine Learning", "Deep Learning", "Pandas", "NumPy", "TensorFlow", "PyTorch", "Tableau", "Git"],
        "product manager": ["Product Management", "Agile", "Scrum", "SQL", "Tableau", "Agile Roadmap", "System Design", "DevOps"],
        "devops engineer": ["AWS", "Docker", "Kubernetes", "Jenkins", "Linux", "Bash", "Terraform", "Ansible", "Git", "Python", "CI/CD"],
        "full stack developer": ["JavaScript", "HTML", "CSS", "React", "Node.js", "Express", "MongoDB", "SQL", "Git", "TypeScript", "AWS"],
    }
    
    role_key = "software engineer"
    for k in role_skills_map.keys():
        if k in role.lower():
            role_key = k
            break
            
    base_skills = role_skills_map[role_key]
    jobs = []
    
    for i in range(25):
        company = random.choice(mock_companies)
        city = random.choice(mock_cities)
        exp = random.choice(["0-2 years", "2-5 years", "5+ years"])
        salary = estimate_salary_for_role(role, exp) * random.uniform(0.9, 1.2)
        
        num_skills = random.randint(4, 8)
        selected_skills = random.sample(base_skills, min(num_skills, len(base_skills)))
        
        jobs.append({
            "id": f"mock_{role_key}_{i}",
            "job_id": f"mock_{role_key}_{i}",
            "title": f"{exp.split()[0]} {role.title()}",
            "company_name": company,
            "location": f"{city}, India",
            "experience": exp,
            "final_salary": round(salary, 2),
            "skills": ", ".join(selected_skills),
            "description": f"Exciting job opening for a {role} at {company} in {city}. Candidate should have strong skills in {', '.join(selected_skills[:3])}."
        })
        
    return jobs
