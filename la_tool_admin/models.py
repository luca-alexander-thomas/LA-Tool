from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    SOURCE_LOCAL = 'local'
    SOURCE_DIVERA = 'divera'
    SOURCE_ENTRA = 'entra'
    SOURCE_CHOICES = [
        (SOURCE_LOCAL, 'Lokal'),
        (SOURCE_DIVERA, 'Divera'),
        (SOURCE_ENTRA, 'Microsoft Entra'),
    ]

    # Divera qualification ID → (full name, short name)
    # IDs are specific to THW-Jugend Gelsenkirchen (Divera cluster 20369)
    QUAL_MAP = {
        24130: ('Jugendbetreuer', 'JUB'),
        24131: ('Jugendhelfer', 'JHE'),
        24135: ('Jugendhelfersprecher', 'JHEsp'),
        30132: ('LA Bronze', 'LA B'),
        30133: ('LA Silber', 'LA S'),
        30134: ('LA Gold', 'LA G'),
        32453: ('Junghelfer+', 'JHE+'),
    }
    LA_QUAL_IDS = {30132: 'bronze', 30133: 'silber', 30134: 'gold'}

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    login_source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_LOCAL
    )
    divera_api_key = models.CharField(max_length=255, blank=True)
    divera_qualifications = models.JSONField(blank=True, null=True)
    divera_groups = models.JSONField(blank=True, null=True)
    divera_ucr = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.user.username

    @property
    def divera_la_level(self):
        """Return highest LA-Stufe as 'bronze'/'silber'/'gold', or None."""
        if not self.divera_qualifications:
            return None
        for qual_id, level in [(30134, 'gold'), (30133, 'silber'), (30132, 'bronze')]:
            if qual_id in self.divera_qualifications:
                return level
        return None

    @property
    def divera_la_display(self):
        return {'bronze': 'LA Bronze', 'silber': 'LA Silber', 'gold': 'LA Gold'}.get(
            self.divera_la_level
        )

    @property
    def divera_qualification_details(self):
        """Return list of {id, name, shortname} for each stored qualification."""
        if not self.divera_qualifications:
            return []
        result = []
        for q_id in self.divera_qualifications:
            name, short = self.QUAL_MAP.get(q_id, (f'Qual #{q_id}', '?'))
            result.append({'id': q_id, 'name': name, 'shortname': short})
        return result


class DiveraQualification(models.Model):
    qual_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.qual_id})'


class AutoGroupRule(models.Model):
    """Links a Django auth.Group to Divera qual IDs and/or Entra group IDs for auto-membership."""
    group = models.OneToOneField(
        'auth.Group', on_delete=models.CASCADE, related_name='auto_rule'
    )
    divera_qual_ids = models.JSONField(default=list, blank=True)
    entra_group_ids = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.group.name


class Changes(models.Model):
    change = models.CharField(max_length=200)
    datetime = models.DateTimeField(auto_now=True)
    username = models.CharField(max_length=100)
    additional_meta = models.JSONField()

    def __str__(self):
        return self.change
