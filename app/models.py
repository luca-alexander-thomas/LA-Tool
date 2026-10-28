from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator

_PDF_IMAGE_VALIDATOR = FileExtensionValidator(allowed_extensions=['pdf', 'png', 'jpg', 'jpeg'])


class Levels(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, max_length=50)
    order = models.IntegerField()
    icon = models.ImageField(upload_to='levels/', blank=True, null=True)
    badge_bg_class = models.CharField(max_length=50, blank=True, default='')
    badge_text_class = models.CharField(max_length=50, blank=True, default='')
    default_training_count = models.PositiveIntegerField(default=10)
    default_training_pass_pct = models.PositiveIntegerField(default=75)
    default_exam_count = models.PositiveIntegerField(default=20)
    default_exam_pass_pct = models.PositiveIntegerField(default=75)
    is_draft = models.BooleanField(default=False)

    class Meta:
        ordering = ['order']
        permissions = [
            ('manage_levels', 'Stufen verwalten'),
        ]

    @property
    def next_level(self):
        return Levels.objects.filter(order__gt=self.order).order_by('order').first()

    def __str__(self):
        return self.name


class TrainingResultData(models.Model):
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name


class ExamResultData(models.Model):
    name = models.CharField(max_length=100)
    questions = models.JSONField(blank=True, null=True)
    answers = models.JSONField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True)
    exam = models.ForeignKey(
        'Exams', on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    state = models.CharField(max_length=20, choices=[(
        'hidden', 'Hidden'), ('published', 'Published'), ('archived', 'Archived')], default='hidden')

    def __str__(self):
        return self.name


class Questions_Catalogs(models.Model):
    SCORING_ALL_OR_NOTHING = 'all_or_nothing'
    SCORING_PARTIAL = 'partial'
    SCORING_CHOICES = [
        (SCORING_ALL_OR_NOTHING, 'Alles oder nichts'),
        (SCORING_PARTIAL, 'Teilpunkte'),
    ]

    title = models.CharField(max_length=100)
    short_title = models.CharField(max_length=20)
    level = models.ForeignKey(Levels, on_delete=models.SET_NULL, null=True, blank=True)
    icon = models.ImageField(
        upload_to='ICONs/', blank=True, null=True)
    multi_answer_scoring = models.CharField(
        max_length=20, choices=SCORING_CHOICES, default=SCORING_ALL_OR_NOTHING,
    )
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    is_draft = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('manage_catalogs', 'Kataloge verwalten'),
        ]

    def __str__(self):
        return self.title


class Questions_Theory(models.Model):
    number = models.CharField(max_length=20, blank=True, null=True)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    answer_text = models.TextField()
    answer_correct = models.JSONField(blank=True, null=True)
    answer_choice = models.JSONField(blank=True, null=True)
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    is_draft = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('manage_theory', 'Theoriefragen verwalten'),
        ]

    @property
    def correct_answers(self):
        if self.answer_correct:
            return self.answer_correct
        if self.answer_text:
            return [self.answer_text]
        return []

    @property
    def is_multi_answer(self):
        return len(self.correct_answers) > 1

    def __str__(self):
        return self.question


class Questions_Practical(models.Model):
    number = models.CharField(max_length=20, blank=True, null=True)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(
        upload_to='Aufgaben-Praktisch/', blank=True, null=True,
        validators=[_PDF_IMAGE_VALIDATOR])
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    is_draft = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('manage_practical', 'Praktische Aufgaben verwalten'),
        ]

    def __str__(self):
        return self.question


class Questions_GroupExercise(models.Model):
    number = models.CharField(max_length=20)
    question = models.TextField()
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(
        upload_to='Aufgaben-Gruppe/', blank=True, null=True,
        validators=[_PDF_IMAGE_VALIDATOR])
    help_reference = models.TextField(blank=True, null=True)
    meta_reference = models.JSONField(blank=True, null=True)
    meta_time = models.DateTimeField(auto_now_add=True)
    is_draft = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('manage_group_exercises', 'Gruppenaufgaben verwalten'),
        ]

    def __str__(self):
        return self.question


class PracticalSelfAssessment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practical_assessments')
    question = models.ForeignKey(Questions_Practical, on_delete=models.CASCADE, related_name='assessments')
    score = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'question')]

    def __str__(self):
        return f'{self.user} — {self.question}: {self.score}'


class GroupExerciseSelfAssessment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_assessments')
    question = models.ForeignKey(Questions_GroupExercise, on_delete=models.CASCADE, related_name='assessments')
    score = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'question')]

    def __str__(self):
        return f'{self.user} — {self.question}: {self.score}'


@receiver(pre_delete, sender=Questions_Practical)
def delete_practical_file(sender, instance, **kwargs):
    if not instance.file:
        return
    # Only delete the physical file if no other practical question references it
    shared = Questions_Practical.objects.filter(
        file=instance.file.name
    ).exclude(pk=instance.pk).exists()
    if not shared:
        instance.file.delete(save=False)


@receiver(pre_delete, sender=Questions_GroupExercise)
def delete_group_file(sender, instance, **kwargs):
    if not instance.file:
        return
    # Only delete the physical file if no other group exercise references it
    shared = Questions_GroupExercise.objects.filter(
        file=instance.file.name
    ).exclude(pk=instance.pk).exists()
    if not shared:
        instance.file.delete(save=False)


@receiver(pre_delete, sender=Levels)
def delete_level_icon(sender, instance, **kwargs):
    if instance.icon:
        instance.icon.delete(save=False)


class Exams(models.Model):
    name = models.CharField(max_length=100)
    level = models.ForeignKey(
        Levels, on_delete=models.SET_NULL, null=True, blank=True)
    catalog = models.ForeignKey(
        Questions_Catalogs, on_delete=models.SET_NULL, null=True, blank=True)
    time_in_min = models.IntegerField(null=True)
    pass_threshold = models.IntegerField(default=0, help_text='Mindestpunktzahl zum Bestehen (0 = kein Minimum)')
    info_text = models.TextField(blank=True, default='')
    end_text = models.TextField(blank=True, default='')
    visible = models.BooleanField(default=False)
    closed = models.BooleanField(default=True)
    archived = models.BooleanField(default=False)
    assigned_users = models.ManyToManyField(
        User, blank=True, related_name='assigned_exams')
    assigned_groups = models.ManyToManyField(
        'auth.Group', blank=True, related_name='assigned_exams')
    questions = models.ManyToManyField(
        Questions_Theory, blank=True, related_name='exams')

    class Meta:
        permissions = [
            ('manage_exams', 'Prüfungen verwalten'),
            ('view_exam_results', 'Prüfungsergebnisse einsehen'),
            ('release_exam_results', 'Prüfungsergebnisse freigeben'),
        ]

    def __str__(self):
        return self.name


class Work(models.Model):
    title = models.CharField(max_length=100)
    date = models.DateTimeField()
    date_end = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='')
    level = models.ForeignKey(
        Levels, on_delete=models.SET_NULL, null=True, blank=True)
    theory_questions = models.ManyToManyField(
        Questions_Theory, blank=True, related_name='works')
    practical_exercises = models.ManyToManyField(
        Questions_Practical, blank=True, related_name='works')
    group_exercises = models.ManyToManyField(
        Questions_GroupExercise, blank=True, related_name='works')
    divera_id = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    groups = models.ManyToManyField('auth.Group', blank=True, related_name='works')
    is_manual = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('manage_work', 'Dienste verwalten'),
            ('sync_divera_work', 'Dienste aus Divera synchronisieren'),
        ]

    def __str__(self):
        return self.title


class SiteSettings(models.Model):
    training_pass_threshold = models.IntegerField(
        default=75, help_text='Mindestprozentsatz (0–100) zum Bestehen eines Trainings')

    class Meta:
        verbose_name = 'Site-Einstellungen'
        permissions = [
            ('access_admin', 'Admin-Bereich zugreifen'),
            ('manage_settings', 'Einstellungen verwalten'),
            ('manage_users', 'Nutzer verwalten'),
            ('manage_groups', 'Gruppen und Berechtigungen verwalten'),
        ]

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
