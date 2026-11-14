# Releases, packages, and hosting

## GitHub release and container

The publishing workflow runs after a successful CI run on trusted pushes to main. It reads the version from `pyproject.toml`, requires matching release notes, builds a Python wheel/source archive and a PostgreSQL-capable container, verifies the distribution contents, and publishes a versioned GitHub release with checksums and an immutable container digest.

Already published versions are skipped. Bump the project version and add `docs/releases/vX.Y.Z.md` to prepare another release. Published version tags are not moved or rewritten by the workflow.

The container is associated with this repository using its OCI source label. GitHub initially makes new container packages private, even when their source repository is public. In the package's settings, an owner can choose Public to allow anonymous pulls. A public package can then be pulled with:

```bash
docker pull ghcr.io/reburn9/sturdy-octo-chainsaw:0.1.1
```

For a private package, authenticate to GHCR using your own authorized account before pulling. Never put tokens in repository files or shell command arguments. The publishing jobs use their short-lived GitHub Actions token through standard input.

## Render deployment

Live workspace: https://labelledger-jo67.onrender.com (sign-in required). The verified deployed source commit and service ID are recorded in [`deployment/render.json`](../deployment/render.json).

`render.yaml` declares a free Python web service and free PostgreSQL database in the same region. It enables HTTPS-related Django settings, trusts Render's sanitized forwarding header, and permits the exact hostname supplied by Render. The build installs pinned PostgreSQL dependencies, collects static files, applies migrations, and creates the initial operator from private environment settings.

The initial username is `owner`. Render generates the private `DJANGO_SUPERUSER_PASSWORD`; retrieve it from the service's environment settings. It is never printed by the bootstrap command, committed, or included in a release asset. After creation, bootstrap reruns do not reset credentials, promote an existing ordinary account, or reactivate a disabled operator.

Render also generates a private 256-bit `DJANGO_SECRET_SEED`. The app derives a stable Django signing key from those bytes with a domain-separated SHA-512 digest. This accommodates Render's 44-character base64 value while preserving the minimum length required for an explicit `DJANGO_SECRET_KEY`. Reuse the seed across deploys; rotating it invalidates existing sessions.

The first deployment starts with an empty database. Local synthetic demo accounts are not created on the shared service. Sign in as the owner, create a dataset, and add users deliberately.

**Free-plan limitation:** Render's free PostgreSQL database expires 30 days after creation. Export or migrate any important data before expiration, or explicitly choose suitable paid hosting. The free web service can sleep when idle. This configuration does not authorize an automatic paid upgrade.

The health check is `/health/`. A successful deployment must return an OK database/schema status before it is recorded as a GitHub deployment. A successful build alone is not proof that the application is live.

Once Render reports a successful deployment, record its actual `service_id`, HTTPS `environment_url`, and exact `source_sha` in `deployment/render.json`. Committing that manifest triggers the recording workflow, which rechecks database health before creating a successful `render-demo` deployment on GitHub. Do not add the manifest before a real service has been deployed and verified. No deployment is fabricated merely to populate the sidebar.

After the service is live, enable Releases, Deployments, and Packages in the repository's About settings and set Website to the actual deployment URL. These display settings do not create release artifacts, a registry package, or a hosted service by themselves.

References: [Render Django deployment](https://render.com/docs/deploy-django), [Render free plans](https://render.com/docs/free), and [GitHub package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).
