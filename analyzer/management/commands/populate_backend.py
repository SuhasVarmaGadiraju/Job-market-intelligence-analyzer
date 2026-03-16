import re

from django.core.management.base import BaseCommand
from django.db.models import Avg, Min, Max

from analyzer.models import Job, Role, Skill, SalaryData


class Command(BaseCommand):
    help = "Populate Role, Skill, and SalaryData tables from existing Job records."

    def handle(self, *args, **options):
        skill_split_re = re.compile(r"[\n\r,;|/•]+")

        titles_qs = (
            Job.objects.exclude(title__isnull=True)
            .exclude(title__exact="")
            .values_list("title", flat=True)
            .distinct()
        )
        titles = list(titles_qs)

        roles_created = 0
        roles_existing = 0
        skills_created = 0
        salary_created = 0
        salary_updated = 0
        jobs_linked = 0

        for title in titles:
            role_name = (title or "").strip()
            if not role_name:
                continue

            role_obj, created = Role.objects.get_or_create(name=role_name)
            if created:
                roles_created += 1
            else:
                roles_existing += 1

            # Link jobs to role for easier querying going forward (safe + idempotent)
            jobs_linked += Job.objects.filter(title=role_name, role__isnull=True).update(role=role_obj)

            # Salary aggregates from Job.final_salary (null-safe)
            salary_aggs = (
                Job.objects.filter(title=role_name)
                .exclude(final_salary__isnull=True)
                .filter(final_salary__gt=0)
                .aggregate(
                    min_salary=Min("final_salary"),
                    max_salary=Max("final_salary"),
                    avg_salary=Avg("final_salary"),
                )
            )

            avg_salary = salary_aggs.get("avg_salary")
            if avg_salary is not None:
                avg_salary_int = int(round(float(avg_salary)))
                obj, s_created = SalaryData.objects.update_or_create(
                    role=role_obj,
                    experience_level="All",
                    defaults={"average_salary": avg_salary_int},
                )
                if s_created:
                    salary_created += 1
                else:
                    salary_updated += 1

            # Skills: parse comma-separated text from Job.skills
            role_jobs = Job.objects.filter(title=role_name).only("skills")
            for job in role_jobs.iterator(chunk_size=2000):
                raw = (job.skills or "").strip()
                if not raw:
                    continue
                parts = [p.strip() for p in skill_split_re.split(raw) if p.strip()]
                for p in parts:
                    if not p:
                        continue
                    _, sk_created = Skill.objects.get_or_create(role=role_obj, name=p)
                    if sk_created:
                        skills_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                "populate_backend completed: "
                f"roles_created={roles_created}, roles_existing={roles_existing}, "
                f"skills_created={skills_created}, "
                f"salary_created={salary_created}, salary_updated={salary_updated}, "
                f"jobs_linked={jobs_linked}"
            )
        )
