from django.contrib import admin
from .models import Role, Skill, Job, SalaryData

admin.site.register(Role)
admin.site.register(Skill)
admin.site.register(Job)
admin.site.register(SalaryData)