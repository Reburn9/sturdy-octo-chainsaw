"""Record an observed Render deployment only after verifying its live health endpoint."""

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def github_post(endpoint, payload):
    result = subprocess.run(
        ["gh", "api", "--method", "POST", endpoint, "--input", "-"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def main():
    data = json.loads(Path("deployment/render.json").read_text())
    url, sha = data["environment_url"], data["source_sha"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".onrender.com"):
        raise SystemExit("Use the verified HTTPS Render service URL.")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SystemExit(
            "Use the service origin only, without credentials, paths, or query parameters."
        )
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit(
            "Provide the exact source commit reported by Render's successful deployment."
        )
    with urlopen(url.rstrip("/") + "/health/", timeout=60) as response:
        if response.status != 200 or json.load(response).get("status") != "ok":
            raise SystemExit("Render application did not pass its database/schema health check.")
    repo = os.environ["GITHUB_REPOSITORY"]
    deployment = github_post(
        f"repos/{repo}/deployments",
        {
            "ref": sha,
            "auto_merge": False,
            "required_contexts": [],
            "environment": "render-demo",
            "description": "LabelLedger Python application on Render",
            "production_environment": False,
            "transient_environment": False,
            "payload": {"provider": "Render", "service_id": data["service_id"]},
        },
    )
    github_post(
        f"repos/{repo}/deployments/{deployment['id']}/statuses",
        {
            "state": "success",
            "environment_url": url,
            "auto_inactive": True,
            "log_url": f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            "description": "Render reported a successful deploy; database health check passed.",
        },
    )
    print(f"Recorded healthy Render deployment: {url}")


if __name__ == "__main__":
    main()
