from django.apps import AppConfig


class AnalyzerConfig(AppConfig):
    name = 'analyzer'

    def ready(self):
        # We now use Live API + On-demand Caching.
        # Pre-computation at startup is disabled for optimal performance.
        pass
