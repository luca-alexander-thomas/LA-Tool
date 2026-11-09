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
    divera_qualifications = models.JSONField(blank=True, null=True)
    divera_groups = models.JSONField(blank=True, null=True)
    # Feste Divera-ID (User-Cluster-Relation am Standort): darüber wird ein Divera-Login dem Konto zugeordnet
    divera_ucr = models.IntegerField(blank=True, null=True)
    # Zeitpunkt, zu dem das Konto deaktiviert wurde, weil die Person nicht mehr im Divera-Standort ist
    divera_left_at = models.DateTimeField(blank=True, null=True)
    # Stand schon einmal in der Personenliste des Standorts (Admin-Key). Fehlt die Person später darin,
    # ist sie ausgetreten; wer nie darin stand (z.B. reine Verwaltungskonten), wird nicht gesperrt.
    divera_listed = models.BooleanField(default=False)
    # Feste Entra-ID (Object-ID); verhindert, dass ein anderes Entra-Konto mit gleicher Mail das Konto übernimmt
    entra_oid = models.CharField(max_length=64, blank=True, default='')
    # Zuletzt bekannte Entra-Gruppen (Object-IDs); None = nie per Entra angemeldet
    entra_group_ids = models.JSONField(blank=True, null=True)
    # Wöchentliche Push-Erinnerung an fällige Wiederholungen (Befehl send_learning_reminders)
    learning_reminders = models.BooleanField(default=True)
    last_learning_reminder_at = models.DateTimeField(blank=True, null=True)

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


class PinnedGroup(models.Model):
    """Lokal festgesetzte Gruppenmitgliedschaft: Der IdP-Abgleich (Entra/Divera) entfernt sie nie."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pinned_groups')
    group = models.ForeignKey('auth.Group', on_delete=models.CASCADE, related_name='pinned_members')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'group'], name='unique_pinned_group')]

    def __str__(self):
        return f'{self.user} → {self.group}'


class Changes(models.Model):
    change = models.CharField(max_length=200)
    datetime = models.DateTimeField(auto_now=True)
    username = models.CharField(max_length=100)
    additional_meta = models.JSONField()

    def __str__(self):
        return self.change


class PushSubscription(models.Model):
    """Ein Gerät/Browser, das Web-Push-Benachrichtigungen für einen Nutzer empfängt."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_subscriptions')
    # max_length 700: passt in einen MySQL-Unique-Index (utf8mb4)
    endpoint = models.URLField(max_length=700, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user} – {self.user_agent[:40]}'


class UserNotification(models.Model):
    """Gespeicherte Benachrichtigung (Posteingang, Zähler an Glocke und App-Symbol).

    Wird bei jedem Push angelegt – auch für Nutzer ohne Push-Gerät, damit sie die Nachricht in der App sehen.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=500, blank=True, default='')
    url = models.CharField(max_length=300, default='/')
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['user', 'read_at'])]

    def __str__(self):
        return f'{self.user} – {self.title}'
