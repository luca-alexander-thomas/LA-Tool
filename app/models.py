from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import pre_delete
from django.dispatch import receiver


class Levels(models.Model):
    level_name = models.CharField(max_length=100)
    level_complexity = models.IntegerField()

    def __str__(self):
        return self.level_name

class TrainingResultData(models.Model):  # TrainingData
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name


class ExamResultData(models.Model):  # ExamData
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True)
    state = models.CharField(max_length=20, choices=[(
        'hidden', 'Hidden'), ('published', 'Published'), ('archived', 'Archived')], default='hidden')

    def __str__(self):
        return self.name


class Questions_Catalogs(models.Model):  # Questions_Theory_Catalogs
    title = models.CharField(max_length=100)
    short_title = models.CharField(max_length=20)
    complexity = models.CharField(max_length=20, choices=[(
        'bronze', 'LA-Bronze'), ('silber', 'LA-Silber'), ('gold', 'LA-Gold')], default='bronze')
    level = models.ForeignKey(Levels, on_delete=models.SET_NULL, null=True)
    icon = models.ImageField(
        upload_to='ICONs/', blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title



class Questions_Theory(models.Model):
    number = models.CharField(max_length=20, blank=True, null=True)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    answer_text = models.TextField()
    answer_choice = models.JSONField(blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question


class Questions_Practical(models.Model):
    number = models.CharField(max_length=20, blank=True, null=True)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(
        upload_to='Aufgaben-Praktisch/', blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question


class Questions_GroupExercise(models.Model):
    number = models.CharField(max_length=20)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(
        upload_to='Aufgaben-Gruppe/', blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question


@receiver(pre_delete, sender=Questions_Practical)
def delete_practical_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(pre_delete, sender=Questions_GroupExercise)
def delete_group_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


class Exams(models.Model):
    name = models.CharField(max_length=100)
    level = models.ForeignKey(Levels, on_delete=models.SET_NULL, null=True)
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.SET_NULL, null=True)
    time_in_min = models.IntegerField(null=True)
    info_text = models.TextField()
    end_text = models.TextField()
    visible = models.BooleanField(default=False)
    closed = models.BooleanField(default=True)
    archived = models.BooleanField(default=False)
    assigned_user_ids = models.JSONField()
    questions = models.JSONField()

    def __str__(self):
        return self.name


class Work(models.Model):
    title = models.CharField(max_length=100)
    date = models.DateTimeField()
    description = models.TextField()
    theory_question = models.JSONField()
    practical_exercises = models.JSONField()
    group_exercises = models.JSONField()
    created_at = models.DateTimeField()
    created_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
