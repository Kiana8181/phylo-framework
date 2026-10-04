# Async orchestration and upload tests

The former infrastructure blockers have been addressed. See [TESTING.md](TESTING.md)
for setup, the complete matrix, isolated Docker services and coverage reports.

```bash
npm test                  # Unit + real PostgreSQL/MinIO integration + coverage
npm run test:all -- --build # Also scientific methods, R suites and Chromium
```

The queue suite uses actual migrations and PostgreSQL row locks, including
concurrent worker claims, fairness, quota, cancellation and expired leases.
Worker tests use a real database with controlled remote job responses to exercise
retry/resume/error paths deterministically. Scientific E2E uses real method jobs.

Python process lifecycle tests now run against **each** of GCtree and ClonalTree;
R tests start and cancel real child process groups in both R method images.
React tests cover upload progress/abort/cleanup and run cancellation UI. Browser
tests submit each method's documented example and inspect its rendered results.

A missing required database/service causes a failure. To run only tests with no
external service dependency:

```bash
.venv/bin/python -m pytest -c pytest.ini -m 'not integration'
npm run test:js
```
