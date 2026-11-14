import base64

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.secret_key import resolve_secret_key


class SecretKeyTests(SimpleTestCase):
    # Public test data, never a deployment credential.
    seed = base64.b64encode(bytes(range(32))).decode()

    def test_platform_seed_is_stable_and_suitable_for_django(self):
        environ = {"DJANGO_SECRET_SEED": self.seed}
        key = resolve_secret_key(environ, debug=False)
        self.assertEqual(key, resolve_secret_key(environ, debug=False))
        self.assertGreaterEqual(len(key), 50)
        self.assertNotIn(self.seed, key)
        different = base64.b64encode(bytes(range(1, 33))).decode()
        self.assertNotEqual(key, resolve_secret_key({"DJANGO_SECRET_SEED": different}, debug=False))

    def test_explicit_keys_remain_unchanged(self):
        key = "existing-private-key-" + "x" * 50
        self.assertEqual(
            key,
            resolve_secret_key(
                {"DJANGO_SECRET_KEY": key, "DJANGO_SECRET_SEED": self.seed}, debug=False
            ),
        )

    def test_invalid_or_short_seeds_fail_without_echoing_them(self):
        for seed in ["sensitive-invalid-seed", base64.b64encode(b"too short").decode()]:
            with self.subTest(seed_length=len(seed)):
                with self.assertRaises(ImproperlyConfigured) as error:
                    resolve_secret_key({"DJANGO_SECRET_SEED": seed}, debug=False)
                self.assertNotIn(seed, str(error.exception))

    def test_production_rejects_missing_and_weak_keys(self):
        for environ in [
            {},
            {"DJANGO_SECRET_KEY": "short"},
            {"DJANGO_SECRET_KEY": "django-insecure-" + "x" * 60},
        ]:
            with self.assertRaises(ImproperlyConfigured):
                resolve_secret_key(environ, debug=False)
        self.assertTrue(resolve_secret_key({}, debug=True).startswith("django-insecure-"))
