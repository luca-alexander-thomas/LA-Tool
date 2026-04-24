from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    divera_api_key = models.CharField(max_length=64, blank=True)
    divera_qualifications = models.JSONField(blank=True, null=True)
    divera_groups = models.JSONField(blank=True, null=True)
    divera_ucr = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.user.username


class Changes(models.Model):
    change = models.CharField(max_length=200)
    datetime = models.DateTimeField(auto_now=True)
    username = models.CharField(max_length=100)
    additional_meta = models.JSONField()

    def __str__(self):
        return self.change
