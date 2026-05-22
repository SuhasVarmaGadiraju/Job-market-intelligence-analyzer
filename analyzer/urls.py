from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('', views.home, name='home'),

    path('dashboard/', views.dashboard, name='dashboard'),
    path('role-intelligence/', views.role_intelligence, name='role_intelligence'),
    path('role/', views.role, name='role'),
    path('role/search/', views.role_search, name='role_search'),
    path('role/analytics-data/', views.role_analytics_data, name='role_analytics_data'),
    path('api/search-roles/', views.api_search_roles, name='api_search_roles'),
    path('skill-gap/', views.skill_gap, name='skill_gap'),
    path('skill-gap/analyze/', views.skill_gap_analyze, name='skill_gap_analyze'),
    path('salary/', views.salary, name='salary'),
    path('salary/insights-data/', views.salary_insights_data, name='salary_insights_data'),
    path('dashboard/data/', views.dashboard_data, name='dashboard_data'),
    path('trend-tracking/', views.trend_tracking, name='trend_tracking'),
    path('trend-tracking/data/', views.trend_tracking_data, name='trend_tracking_data'),
    path('profile/', views.profile, name='profile'),
    path('settings/', views.settings, name='settings'),

    path('activity/', views.activity, name='activity'),
    path(
        'password/change/',
        auth_views.PasswordChangeView.as_view(template_name='analyzer/password_change_form.html'),
        name='password_change',
    ),
    path(
        'password/change/done/',
        auth_views.PasswordChangeDoneView.as_view(template_name='analyzer/password_change_done.html'),
        name='password_change_done',
    ),
]