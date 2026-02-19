from django.db import models
from django.contrib.auth.models import User

class TrainingData(models.Model):
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)


    def __str__(self):
        return self.name
    
class ExamData(models.Model):
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    state = models.CharField(max_length=20, choices=[('hidden', 'Hidden'), ('published', 'Published'), ('archived', 'Archived')], default='hidden')

    def __str__(self):
        return self.name
    
class Questions_Theory_Catalogs(models.Model):
    name = models.CharField(max_length=100)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
class Questions_Theory(models.Model):
    question = models.TextField()
    catalog = models.ForeignKey(Questions_Theory_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    answer_text = models.TextField()
    answer_choice = models.JSONField(blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question
    
class Questions_Practical(models.Model):
    question = models.TextField()
    file = models.FileField(upload_to='Aufgaben-Praktisch/', blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        self.file.delete()
        super(Questions_Practical, self).delete(*args, **kwargs)

    def __str__(self):
        return self.question
    
