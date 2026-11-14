"""Verify distributable assets before publishing a release."""

import hashlib
import zipfile
from pathlib import Path


def main():
    wheels = list(Path("dist").glob("*.whl"))
    archives = list(Path("dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(archives) != 1:
        raise SystemExit("Expected exactly one wheel and one source archive.")
    expected = {
        "config/settings.py",
        "config/wsgi.py",
        "ledger/migrations/0001_initial.py",
        "ledger/templates/ledger/dashboard.html",
        "ledger/static/ledger/app.css",
        "ledger/management/commands/bootstrap_admin.py",
    }
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        if missing := expected - names:
            raise SystemExit(f"Missing application files in wheel: {sorted(missing)}")
        if any(name.endswith((".sqlite3", "/.env")) for name in names):
            raise SystemExit("Runtime data must not be included in the wheel.")
    checksum_lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(Path("dist").iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    Path("dist/SHA256SUMS").write_text("\n".join(checksum_lines) + "\n")
    print("Distribution contents verified and SHA256SUMS generated.")


if __name__ == "__main__":
    main()
