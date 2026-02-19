from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    divera_api_key = models.CharField(max_length=64, blank=True)
    website = models.URLField(blank=True)
    location = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return self.user.username
