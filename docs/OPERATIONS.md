# Operating LabelLedger

## Local development

The default settings use loopback hosts, a development-only secret, debug mode, and SQLite in `db.sqlite3`. The `.gitignore` excludes databases, environment files, generated static files, and local credentials. Environment variables are read from the process; a `.env` file is **not automatically loaded** by Django.

Use the README's virtual environment instructions or the optional local container:

```bash
docker compose up --build
docker compose exec web python manage.py seed_demo
```

The seed command prints fresh local demo credentials. The Compose service binds only to `127.0.0.1` and stores SQLite in a named volume. Stop it with `docker compose down`; this keeps the data volume. Do not use `down -v` unless you intend to remove that local database.

The Dockerfile is also an application-server image with a non-root user and collected static assets. The Compose override intentionally uses development settings; it is not a production recipe.

## Environment settings

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_DEBUG` | `1` | Set to `0` outside local development |
| `DJANGO_SECRET_KEY` | Local development fallback only | Required private key of at least 50 characters when debug is off |
| `DJANGO_SECRET_SEED` | Unset | Alternative to the explicit key: base64-encoded private random bytes (at least 32 bytes). A domain-separated SHA-512 digest produces a stable Django key. Render generates this seed privately. Explicit `DJANGO_SECRET_KEY` takes precedence. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Comma-separated allowed hostnames, without URL schemes |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Empty | Optional comma-separated HTTPS origins for a trusted cross-origin deployment |
| `DJANGO_TRUST_PROXY` | `0` | Trust `X-Forwarded-Proto` only behind a proxy that strips untrusted forwarded headers |
| `SQLITE_PATH` | `db.sqlite3` in the repository | Local SQLite path when `DATABASE_URL` is absent |
| `DATABASE_URL` | Empty | Optional `postgresql://user:password@host:5432/database` |
| `DATABASE_SSLMODE` | `prefer` | Set `require` or a verified TLS mode for the intended PostgreSQL service |

Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(64))"`, then store it in your deployment's secret manager. Do not commit it or put it into a URL.

Debug-off settings enforce HTTPS redirects, secure session/CSRF cookies, HSTS, content-type sniffing protection, and frame denial. HSTS includes subdomains and is preload-capable: enable this deployment only for a domain whose subdomains all support HTTPS. When a trusted TLS proxy is used, configure its header sanitization before setting `DJANGO_TRUST_PROXY=1`.

## PostgreSQL

Install the optional driver using `python -m pip install '.[postgres]'`, set `DATABASE_URL`, and run migrations. The URL's credentials must be URL-encoded when they contain reserved characters. The database should be provisioned with an application-specific account and a backup policy. URL query options are not interpreted; TLS is controlled by `DATABASE_SSLMODE`.

CI runs the behavior suite against PostgreSQL as well as SQLite. Changing `DATABASE_URL` does **not** move an existing SQLite database's contents. Plan and verify a data migration separately when switching a live installation.

## Before exposing a shared service

1. Use a trusted TLS reverse proxy, explicit hosts, a private secret, debug off, and a real application server. The image's Gunicorn command is suitable for Linux containers.
2. Use PostgreSQL for concurrent team workloads. Set a reverse-proxy upload limit matching the 5 MiB application contract, with room for multipart overhead, and request timeouts appropriate to synchronous imports.
3. Apply login rate limiting at the proxy or identity perimeter; the application does not currently implement lockout, MFA, password reset, or self-service account enrollment.
4. Run `python manage.py migrate`, `python manage.py collectstatic --noinput`, and `python manage.py check --deploy` under the intended environment. Never seed demonstration accounts into the shared service.
5. Back up the database, test restoration, and configure error monitoring that does not log dataset contents, passwords, cookies, or full database URLs.

`GET /health/` returns 200 only if the database and dataset table can be queried; it returns 503 without exposing connection details on failure. Through an HTTPS-enforcing deployment, use an HTTPS health endpoint or a correctly sanitized trusted-proxy request.

## Accounts and access

`createsuperuser` creates an operator with access to all datasets. `create_reviewer USERNAME --name "Display name"` creates an ordinary active account and prints a generated password. Share that password privately. A dataset manager adds the account to a dataset and chooses its role in Members. A normal user can also create a separate dataset they manage.

Use Django's `changepassword USERNAME` command for an operator-mediated reset; there is no web reset flow. Do not disable or demote a reviewer with unfinished assignments until the work is completed: audited reassignment is a planned feature. Superuser database access remains privileged and can bypass application audit protections.

## Data retention and exports

The application has no destructive dataset deletion route. Keep exports in controlled storage, apply your own retention policy, and back up the database before schema upgrades. CSV escapes leading formula markers; JSONL is the faithful text export. Downloads contain current decisions rather than frozen, content-addressed release snapshots. Users should not treat an audit log or a download as proof of regulatory compliance.
