from django.db import models

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)    
    def __str__(self):          
        return self.name

class Skill(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="skills", null=True, blank=True)
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "name"], name="uniq_skill_per_role"),
        ]

class Job(models.Model):
    job_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="jobs", null=True, blank=True)
    title = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    experience = models.CharField(max_length=100, null=True, blank=True)
    final_salary = models.FloatField(null=True, blank=True)
    job_uploaded = models.DateTimeField(null=True, blank=True)
    skills = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    def __str__(self):
        return self.title

class SalaryData(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    average_salary = models.IntegerField()
    experience_level = models.CharField(max_length=50)
    def __str__(self):
        return f"{self.role.name} - {self.experience_level}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "experience_level"], name="uniq_salarydata_role_experience"),
        ]