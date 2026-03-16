from django.apps import AppConfig


class AnalyzerConfig(AppConfig):
    name = 'analyzer'

    def ready(self):
        from analyzer.services.skill_gap_precompute import warm_role_skill_index
        from analyzer.services.salary_insights_precompute import warm_salary_insights_index

        warm_role_skill_index()
        warm_salary_insights_index()
