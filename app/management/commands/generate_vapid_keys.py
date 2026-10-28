import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class Command(BaseCommand):
    help = 'Erzeugt ein VAPID-Schlüsselpaar für Web-Push-Benachrichtigungen (Ausgabe für die .env).'

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, 'big')
        public = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        self.stdout.write('In die .env eintragen (privaten Schlüssel geheim halten, nicht ins Repository):\n')
        self.stdout.write(f'VAPID_PUBLIC_KEY={_b64url(public)}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={_b64url(private)}')
        self.stdout.write('VAPID_SUBJECT=mailto:<kontakt-adresse>')
        self.stdout.write(self.style.WARNING(
            '\nNeue Schlüssel machen bestehende Push-Abos ungültig; Nutzer müssen Push neu aktivieren.'
        ))
