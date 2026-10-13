This directory is intentionally empty of git data.

Set PHYLO_GIT_DIR=config/no-git in .env when the application is deployed from an
archive that has no .git directory. The API image then builds without git
metadata and records, in each run's version information, that the commit is
unknown. See docs/DEPLOYMENT.md, "Version information".
