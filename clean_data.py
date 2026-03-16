import os
import sys
from typing import Optional

import pandas as pd


def _to_numeric(series: pd.Series) -> pd.Series:
    """Convert a Series to numeric safely (non-parsable values become NaN)."""
    return pd.to_numeric(series, errors="coerce")


def _compute_final_salary(df: pd.DataFrame) -> pd.Series:
    """Create final_salary based on salary or the average of minimumSalary/maximumSalary."""
    final = pd.Series(float("nan"), index=df.index, dtype="float64")

    if "salary" in df.columns:
        salary_numeric = _to_numeric(df["salary"])
        final = salary_numeric

    min_col = "minimumSalary"
    max_col = "maximumSalary"
    if min_col in df.columns and max_col in df.columns:
        min_sal = _to_numeric(df[min_col])
        max_sal = _to_numeric(df[max_col])
        avg = (min_sal + max_sal) / 2
        final = final.where(~final.isna(), avg)

    return final


def _clean_skills(value: Optional[str]) -> list[str]:
    """Normalize skills string to a list of cleaned tokens."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []

    text = str(value)
    if not text.strip():
        return []

    parts = [p.strip().lower() for p in text.split(",")]
    return [p for p in parts if p]


def main() -> int:
    project_root = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(project_root, "indian-job-market-dataset-2025.xlsx")
    output_path = os.path.join(project_root, "cleaned_job_market_data.csv")

    if not os.path.exists(input_path):
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    df = pd.read_excel(input_path)
    rows_before = len(df)

    if "jobId" in df.columns:
        df = df.drop_duplicates(subset=["jobId"], keep="first")

    if "jobUploaded" in df.columns:
        df["jobUploaded"] = pd.to_datetime(df["jobUploaded"], errors="coerce")

    if "jobDescription" in df.columns:
        df = df.dropna(subset=["jobDescription"])

    df["final_salary"] = _compute_final_salary(df)

    if "tagsAndSkills" in df.columns:
        df["tagsAndSkills"] = df["tagsAndSkills"].fillna("")
        df["cleaned_skills"] = df["tagsAndSkills"].apply(_clean_skills)
    else:
        df["cleaned_skills"] = [[] for _ in range(len(df))]

    rows_after = len(df)
    usable_salary_rows = int(df["final_salary"].notna().sum())

    df.to_csv(output_path, index=False)

    print(f"Total rows before cleaning: {rows_before}")
    print(f"Total rows after cleaning: {rows_after}")
    print(f"Number of usable salary rows: {usable_salary_rows}")
    print(f"Saved cleaned dataset to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
