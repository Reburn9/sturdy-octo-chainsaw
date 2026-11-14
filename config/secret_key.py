import base64
import binascii
import hashlib

from django.core.exceptions import ImproperlyConfigured


def resolve_secret_key(environ, *, debug):
    """Keep explicit keys unchanged; derive a stable key from a private 256-bit seed."""
    key = environ.get("DJANGO_SECRET_KEY", "")
    if not key and (seed := environ.get("DJANGO_SECRET_SEED")):
        try:
            decoded = base64.b64decode(seed, validate=True)
        except (ValueError, binascii.Error):
            raise ImproperlyConfigured(
                "DJANGO_SECRET_SEED must be base64-encoded private random bytes."
            ) from None
        if len(decoded) < 32:
            raise ImproperlyConfigured("DJANGO_SECRET_SEED must contain at least 256 random bits.")
        key = hashlib.sha512(b"labelledger/django-secret/v1\0" + decoded).hexdigest()
    if not key and debug:
        key = "django-insecure-labelledger-local-development-only"
    if not debug and (len(key) < 50 or key.startswith("django-insecure-")):
        raise ImproperlyConfigured(
            "Set DJANGO_SECRET_KEY to a private key of at least 50 characters, "
            "or configure a private DJANGO_SECRET_SEED."
        )
    return key
