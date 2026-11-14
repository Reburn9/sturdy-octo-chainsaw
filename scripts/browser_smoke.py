"""Exercise a disposable workspace through a real browser; never touches the user's database."""

import csv
import io
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-results"


def run_smoke(page, base_url, password):
    def login(username):
        page.goto(base_url + "/")
        if page.get_by_role("button", name="Sign out").count():
            page.get_by_role("button", name="Sign out").click()
        page.get_by_label("Username").fill(username)
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Sign in to workspace").click()
        expect(page.get_by_role("heading", name="Every label deserves confidence.")).to_be_visible()

    login("demo")
    expect(page.get_by_text("Product feedback · sentiment", exact=True)).to_be_visible()
    page.screenshot(path=str(ARTIFACTS / "overview.png"), full_page=True)
    page.get_by_role("link", name="New dataset").click()
    page.get_by_label("Dataset name").fill("Smoke review")
    page.get_by_label("Description").fill("Synthetic browser verification.")
    page.get_by_label("Labels").fill("positive, negative")
    page.get_by_label("Required reviews").fill("2")
    page.get_by_role("button", name="Create dataset").click()
    expect(page.get_by_role("heading", name="Smoke review", exact=True)).to_be_visible()
    dataset_url = page.url
    page.get_by_role("link", name="Import records").click()
    page.get_by_label("CSV or JSONL file").set_input_files(
        {
            "name": "invalid.csv",
            "mimeType": "text/csv",
            "buffer": b"id,text\nbad,\n",
        }
    )
    page.get_by_role("button", name="Validate & import").click()
    expect(page.get_by_text("Row 2:", exact=False)).to_be_visible()
    page.get_by_label("CSV or JSONL file").set_input_files(
        {
            "name": "valid.csv",
            "mimeType": "text/csv",
            "buffer": b"id,text\nsmoke-001,An excellent workflow\nsmoke-002,The old export is broken\n",
        }
    )
    page.get_by_role("button", name="Validate & import").click()
    expect(page.get_by_text("Imported 2 records.", exact=False)).to_be_visible()
    page.get_by_role("link", name="Members", exact=True).click()
    for username in ["maya", "ellis"]:
        page.get_by_label("Username").fill(username)
        page.get_by_label("Role").select_option("reviewer")
        page.get_by_role("button", name="Save membership").click()
        expect(page.get_by_text("Dataset access updated.", exact=True)).to_be_visible()
    for username in ["maya", "ellis"]:
        page.goto(dataset_url)
        page.get_by_role("link", name="Assign reviews", exact=True).click()
        page.get_by_label("Reviewer").select_option(label=username)
        page.get_by_label("Count").fill("2")
        page.get_by_role("button", name="Assign records").click()
        expect(page.get_by_text("Assigned 2 records.", exact=False)).to_be_visible()
    for username, label in [("maya", "positive"), ("ellis", "negative")]:
        login(username)
        page.goto(dataset_url)
        page.get_by_role("link", name="smoke-001", exact=True).click()
        expect(page.get_by_role("heading", name="Independent reviews", exact=True)).to_have_count(0)
        page.get_by_label(label, exact=True).check()
        page.get_by_label("Review note").fill("Independent browser test judgment.")
        page.get_by_role("button", name="Save review", exact=True).click()
        expect(page.get_by_text("Review saved.", exact=True)).to_be_visible()
    login("demo")
    page.goto(dataset_url)
    page.get_by_role("link", name="smoke-001", exact=True).click()
    page.screenshot(path=str(ARTIFACTS / "adjudication.png"), full_page=True)
    page.get_by_label("positive", exact=True).check()
    page.get_by_label("Review note").fill("The wording explicitly praises the workflow.")
    page.get_by_role("button", name="Save final decision", exact=True).click()
    expect(page.get_by_role("heading", name="Decision ready", exact=True)).to_be_visible()
    page.goto(dataset_url)
    with page.expect_download() as download_info:
        page.get_by_role("link", name="↓ CSV", exact=True).click()
    download = download_info.value
    rows = list(csv.DictReader(io.StringIO(Path(download.path()).read_text())))
    assert len(rows) == 1 and rows[0]["id"] == "smoke-001" and rows[0]["label"] == "positive"
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + "/")
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (
        "Mobile horizontal overflow"
    )
    page.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
    page.get_by_role("button", name="Toggle navigation").click()
    page.get_by_role("link", name="My review queue", exact=False).click()
    expect(page.get_by_role("heading", name="One careful review at a time.")).to_be_visible()


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="labelledger-smoke-") as directory:
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.update(
            SQLITE_PATH=str(Path(directory) / "smoke.sqlite3"),
            DJANGO_DEBUG="1",
            DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost",
            DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
        )
        password = secrets.token_urlsafe(20)
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, "manage.py", "seed_demo", "--password", password],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        port = int(os.getenv("SMOKE_PORT", "8765"))
        base_url = f"http://127.0.0.1:{port}"
        with (Path(directory) / "server.log").open("w+") as log:
            server = subprocess.Popen(
                [sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Disposable application server exited early.")
                    try:
                        with urlopen(base_url + "/health/", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Disposable application server did not become ready.")
                with sync_playwright() as playwright:
                    executable = (
                        os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
                        or shutil.which("google-chrome")
                        or shutil.which("chromium")
                    )
                    options = {"executable_path": executable} if executable else {}
                    browser = playwright.chromium.launch(headless=True, **options)
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1080}, device_scale_factor=1
                    )
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    try:
                        run_smoke(page, base_url, password)
                        assert not errors, errors
                    except Exception:
                        page.screenshot(path=str(ARTIFACTS / "failure.png"), full_page=True)
                        raise
                    finally:
                        browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
    print(
        "Browser smoke passed: login, atomic import, roles, assignments, independent votes, adjudication, export, mobile layout."
    )


if __name__ == "__main__":
    main()
