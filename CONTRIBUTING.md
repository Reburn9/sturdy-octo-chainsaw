# Contributing

Set up the virtual environment using the README, install `requirements-dev.txt`, and run the checks before changing behavior. Keep real datasets, credentials, local databases, generated passwords, and private logs outside Git.

```bash
git switch -c feature/describe-the-change
python manage.py test ledger.tests
# Implement a small, reviewable change.
ruff check .
ruff format --check .
python manage.py makemigrations --check --dry-run
coverage run manage.py test ledger.tests
coverage report
git add path/to/changed/files
git commit -m "Describe the resulting behavior"
git push -u origin feature/describe-the-change
```

Use actual commits as work happens. Do not manufacture past activity, performance numbers, contributors, user counts, or test results.

For a schema change, create and commit a migration. Put new workflow rules in services so HTML and API callers share them. Use role checks for writes, scoped queries for reads, and a transaction for a state change plus its audit event. Do not mutate models directly from a new view just to bypass a service invariant.

Behavior tests should exercise correctness or an actual failure mode: competing versions, rollback, permissions, malformed imports, metric definitions, or a user workflow. Avoid tests that merely restate assignments or duplicate framework behavior. Run the optional browser smoke for interface changes.

A useful pull request explains the problem, the resulting behavior, why the chosen approach is reasonable, and the validation performed. Call out data migrations and practical limitations. The project may be developed with an AI assistant, but verify its outputs and be prepared to explain every change you keep.
