import os
import hashlib
import re

import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Avg

from analyzer.models import Job, Role, Skill, SalaryData


class Command(BaseCommand):
    help = "Import cleaned job market dataset (Excel) into Role/Job/Skill/SalaryData models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=None,
            help="Optional path to cleaned dataset (.xlsx). Defaults to project root indian-job-market-dataset-2025.xlsx",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing Role/Job/Skill/SalaryData records before import.",
        )

    def handle(self, *args, **options):
        base_dir = getattr(settings, "BASE_DIR", os.getcwd())
        dataset_path = options.get("path") or os.path.join(str(base_dir), "indian-job-market-dataset-2025.xlsx")
        truncate = bool(options.get("truncate"))

        if not os.path.exists(dataset_path):
            self.stderr.write(self.style.ERROR(f"Dataset file not found: {dataset_path}"))
            return

        df = pd.read_excel(dataset_path)

        if "final_salary" in df.columns:
            df["final_salary"] = pd.to_numeric(df["final_salary"], errors="coerce")
        elif "salary" in df.columns:
            df["salary"] = pd.to_numeric(df["salary"], errors="coerce")

        title_col = None
        for c in ["title", "jobTitle", "role", "job_role"]:
            if c in df.columns:
                title_col = c
                break
        if title_col is None:
            raise ValueError("No title/role column found in dataset. Expected one of: title, jobTitle, role, job_role")

        skills_col = None
        for c in ["cleaned_skills", "skills", "skill", "jobSkills"]:
            if c in df.columns:
                skills_col = c
                break

        df[title_col] = df[title_col].fillna("").astype(str).map(lambda s: s.strip())
        distinct_titles = int(df[df[title_col] != ""][title_col].nunique())
        self.stdout.write(f"Distinct roles/titles in dataset: {distinct_titles}")
        total_rows = len(df)
        self.stdout.write(f"Total rows found: {total_rows}")

        if truncate:
            SalaryData.objects.all().delete()
            Skill.objects.all().delete()
            Job.objects.all().delete()
            Role.objects.all().delete()
            self.stdout.write("Deleted existing Role/Job/Skill/SalaryData records.")

        batch_size = 1000
        buffer = []
        created = 0

        skills_split_re = re.compile(r"[\n\r,;|/]+")

        def normalize_role_name(raw):
            name = "" if pd.isna(raw) else str(raw)
            return name.strip()

        def normalize_skill_name(raw):
            name = str(raw).strip()
            if not name:
                return ""
            return name.lower()

        def parse_skills(raw):
            if raw is None or pd.isna(raw):
                return []
            text = str(raw).strip()
            if not text:
                return []
            if text.startswith("[") and text.endswith("]"):
                text = text[1:-1]
            text = text.replace("'", "").replace('"', "")
            parts = [p.strip() for p in skills_split_re.split(text) if p.strip()]
            dedup = []
            seen = set()
            for p in parts:
                k = normalize_skill_name(p)
                if not k or k in seen:
                    continue
                seen.add(k)
                dedup.append(p.strip())
            return dedup

        def stable_job_key(row):
            parts = [
                str(row.get("jobId") or "").strip(),
                str(row.get(title_col) or "").strip(),
                str(row.get("companyName") or "").strip(),
                str(row.get("location") or "").strip(),
                str(row.get("jobUploaded") or "").strip(),
            ]
            base = "|".join(parts)
            return hashlib.md5(base.encode("utf-8")).hexdigest()

        for idx, row in df.iterrows():
            role_name = normalize_role_name(row.get(title_col))
            if not role_name:
                continue

            role_obj, _ = Role.objects.get_or_create(name=role_name)

            skills_text = ""
            if skills_col:
                raw_skills_value = row.get(skills_col)
                parsed_skills = parse_skills(raw_skills_value)
                if parsed_skills:
                    skills_text = ", ".join(parsed_skills)
                    for s in parsed_skills:
                        Skill.objects.get_or_create(role=role_obj, name=s.strip())

            job_uploaded = row.get("jobUploaded")
            if pd.isna(job_uploaded):
                job_uploaded = None

            final_salary = row.get("final_salary") if "final_salary" in df.columns else row.get("salary")
            if pd.isna(final_salary):
                final_salary = None

            job_id_val = row.get("jobId")
            if pd.isna(job_id_val) or job_id_val is None or str(job_id_val).strip() == "":
                job_id_val = stable_job_key(row)
            else:
                job_id_val = str(job_id_val)

            title_val = "" if pd.isna(row.get(title_col)) else str(row.get(title_col)).strip()
            exp_val = None if pd.isna(row.get("experience")) else str(row.get("experience"))
            company_val = None if pd.isna(row.get("companyName")) else str(row.get("companyName"))
            location_val = None if pd.isna(row.get("location")) else str(row.get("location"))
            desc_val = None if pd.isna(row.get("jobDescription")) else str(row.get("jobDescription"))

            job_obj = Job(
                job_id=job_id_val,
                role=role_obj,
                title=title_val,
                company_name=company_val,
                location=location_val,
                experience=exp_val,
                final_salary=final_salary,
                job_uploaded=job_uploaded,
                skills=skills_text,
                description=desc_val,
            )

            buffer.append(job_obj)

            if len(buffer) >= batch_size:
                Job.objects.bulk_create(buffer, batch_size=batch_size, ignore_conflicts=True)
                created += len(buffer)
                buffer = []
                self.stdout.write(f"Inserted {created}/{total_rows} records...")

        if buffer:
            Job.objects.bulk_create(buffer, batch_size=batch_size, ignore_conflicts=True)
            created += len(buffer)

        self.stdout.write(self.style.SUCCESS(f"Jobs inserted (may include conflicts ignored): {created}"))

        # Build SalaryData aggregates (avg salary by role+experience)
        self.stdout.write("Computing SalaryData aggregates...")
        salary_rows = (
            Job.objects.exclude(final_salary__isnull=True)
            .filter(final_salary__gt=0)
            .values("role_id", "experience")
            .annotate(avg_salary=Avg("final_salary"))
        )

        salary_created = 0
        salary_updated = 0
        for r in salary_rows:
            role_id = r.get("role_id")
            exp = (r.get("experience") or "").strip() or "Unknown"
            avg_sal = r.get("avg_salary")
            if avg_sal is None:
                continue
            avg_sal_int = int(round(float(avg_sal)))
            obj, created_flag = SalaryData.objects.update_or_create(
                role_id=role_id,
                experience_level=exp,
                defaults={"average_salary": avg_sal_int},
            )
            if created_flag:
                salary_created += 1
            else:
                salary_updated += 1

        self.stdout.write(self.style.SUCCESS(f"SalaryData upserted: created={salary_created}, updated={salary_updated}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Totals: Roles={Role.objects.count()} Jobs={Job.objects.count()} Skills={Skill.objects.count()} SalaryData={SalaryData.objects.count()}"
            )
        )
