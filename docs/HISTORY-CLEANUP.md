# Committed configuration: what was found, what to rotate, how to clean the history

Configuration files with real credentials were committed to this repository in
the past. This document says what was found, what has to be replaced at the
providers, what has already been changed in the repository, and how to remove
the files from the history. No credential value appears in it: findings are
identified by a **fingerprint**, the first eight hex characters of the SHA-256
of the value followed by its length. To check a value you hold against one:

```bash
printf %s "$VALUE" | shasum -a 256 | cut -c1-8      # compare with the part before the slash
```

Status on 2026-10-13:

| Step | State |
|---|---|
| Env files and `.DS_Store` no longer tracked, ignore rules fixed, scanner in CI | Done |
| History rewrite | **Published by the repository owner.** Checked afterwards on a fresh mirror clone: all 29 branches and 16 tags are free of the removed files and of any recognisable credential (248 commits) |
| Old history still on GitHub | **Yes, in the 19 pull-request refs** (`refs/pull/*`), which still contain the env files and both provider credentials. Only GitHub Support can remove them (section 4, "After publishing") |
| Credentials replaced at their providers | **Not confirmed.** Only the account owners can do it (section 2). Until then they must be treated as known to everyone with access to the repository |
| Other clones and the server | To be replaced as in section 5 |

Removing a credential from a repository **does not make it secret again**.
Anyone who had access to the repository, or to a clone of it, may have a copy.
Replace the credentials first; cleaning the history is tidying up afterwards.

---

## 1. What was found

Scanned: every version of every file reachable from any branch, tag, the reflog
and the stash of the working repository, and separately a fresh mirror clone of
the GitHub repository (`python3 scripts/scan_secrets.py --history`).

The GitHub repository answers anonymous requests with "not found", so it
appears to be private: exposure is limited to accounts with access to it, and
to every machine it was cloned to.

### On GitHub (in the history of branches and tags)

| What | Fingerprint | Where | First committed |
|---|---|---|---|
| Google OAuth client secret (`GOOGLE_CLIENT_SECRET`) | `1d933a61/35` | `.env`, `apps/api/.env` | env files tracked since 2025-09-06 (`apps/api/.env`) and 2026-02-09 (`.env`); still at the tip of most branches |
| Resend API key (`RESEND_API_KEY`) | `e501d489/36` | `.env`, `apps/api/.env` | same |
| Old token-signing key (`SECRET_KEY`) | `78a6c761/35` | `apps/api/.env`, `apps/api/apps/api/.env` | up to 2026-02 |
| Google OAuth client ID | `8ffeca64/72` | `.env`, `apps/api/.env` | an identifier, not a secret |
| A short database password inside `DATABASE_URL` | `7c80ff65/5` | `apps/api/.env`, `apps/api/apps/api/.env` | one commit, 2026-02-04 |
| Public host names of earlier deployments (`CORS_ORIGINS`, `FRONTEND_URL`, …) | — | `.env` | not secrets |

`apps/api/.env` is in the history of all 45 branches and tags, the root `.env`
in 35 of them. Every other secret-like setting in these files only ever held
the placeholder values of `.env.example`.

Files that should never have been tracked, whatever they contain:
`.env`, `apps/api/.env`, `apps/api/apps/api/.env`, `apps/web/.env`,
`services/brepphylo/.env`, `services/gctree/.env`, and `.DS_Store` files.
The last three env files hold no secrets (local paths only).

### Only on the developer machine (never pushed)

Two `git stash` entries, "server-configs" (2026-08-11) and "server settings"
(2026-02-26), hold copies of a server configuration. The first contains a
complete set of generated secrets: token-signing key, PostgreSQL password,
object-store root password and methods password (48 and 64 hexadecimal
characters each). A stash is local: these values are not on GitHub. They stay
on this machine until the stash entries are dropped (section 6).

---

## 2. Rotate: what the account owners must do

In this order. None of it has been done by the tooling, and none of it can be:
it needs the provider accounts.

1. **Google OAuth client secret.** Google Cloud Console → APIs & Services →
   Credentials → the OAuth 2.0 client used for sign-in → add a new secret,
   put it in the server's `.env` as `GOOGLE_CLIENT_SECRET`, restart the API
   (`docker compose --profile prod up -d`), check that Google sign-in works,
   then delete the old secret in the console. The client ID can stay.
2. **Resend API key.** Resend dashboard → API Keys → revoke the key. Nothing
   needs to be configured afterwards: the application has sent all email over
   SMTP since the SMTP migration and no longer reads `RESEND_API_KEY`. Remove
   the `RESEND_*` lines from the server's `.env`.
3. **Token-signing key.** If any deployment ever ran with the old `SECRET_KEY`
   value, or with a `JWT_SECRET_KEY` that was in a committed file, generate a
   new one (`openssl rand -hex 32`) and set `JWT_SECRET_KEY`. Everyone is
   signed out once; nothing else is lost.
4. **Database and object-store passwords.** Only if a deployed value equals a
   committed one. The committed values are the example placeholders (which the
   production start-up check refuses) and the 5-character password above.
   Compare fingerprints if in doubt.
5. **The server configuration in the stash.** If the values in the
   "server-configs" stash are the ones the server uses today, they were not
   exposed through GitHub. Decide whether to keep that stash; drop it when it
   is no longer needed.

---

## 3. What has already changed in the repository

One ordinary commit on `feat/computimm-hardening`, no history rewritten:

- `.gitignore` ignores `.env` and `.env.*` in every directory (except
  `.env.example`), private-key files and `.DS_Store`. The rule for `.env` had
  been commented out.
- The five tracked env files and two `.DS_Store` files are no longer tracked.
  The files themselves were left on disk where the commit was made.
- `scripts/scan_secrets.py` looks for credentials by their format and for files
  that must not be tracked. CI runs it on every push; `--history` scans every
  revision. It prints kinds, places and fingerprints, never a value.

> **Before pulling this commit into any existing checkout, the server
> included, copy the `.env` file somewhere else.** Git removes a file from the
> working directory when a commit stops tracking it. A checkout whose `.env`
> differs from the committed one makes `git pull` stop with an error instead;
> one whose `.env` is unchanged loses the file silently.
>
> ```bash
> cp .env ~/phylo-framework.env.backup && chmod 600 ~/phylo-framework.env.backup
> git pull
> cp ~/phylo-framework.env.backup .env      # if it is gone
> ```

---

## 4. Removing the files from the history

Rewriting history changes the id of every commit after the first affected one:
here, **all 45 branch and tag ids changed**. Every clone made before it is
incompatible and has to be replaced (section 5). The procedure below is the one
that was used; it is kept so that it can be repeated or checked.

### Before

- Section 2 is done, or at least started: the rewrite protects nobody from a
  credential that is still valid.
- Everyone has pushed their work. Nobody pushes until the rewrite is published.
- Open pull requests are merged or closed. GitHub keeps 19 pull-request refs
  (`refs/pull/*`); after the rewrite their diffs no longer make sense.
- `git-filter-repo` is installed (`pip install git-filter-repo` or
  `brew install git-filter-repo`).

### Rewrite and verify (touches nothing on GitHub)

```bash
git clone --mirror git@github.com:Kiana8181/phylo-framework.git phylo-framework-mirror.git
cp -R phylo-framework-mirror.git phylo-framework-original.git        # untouched copy, for comparison and as a backup

sh scripts/history-cleanup/rewrite-mirror.sh phylo-framework-mirror.git
python3 scripts/history-cleanup/verify-rewrite.py phylo-framework-original.git phylo-framework-mirror.git
```

`rewrite-mirror.sh` removes every file named `.env` (in any directory) and
every `.DS_Store` from every commit. It works only on a bare mirror clone,
never pushes, and leaves the mirror without a remote. `verify-rewrite.py`
compares the result with the untouched copy and fails unless: the same branches
and tags exist; the files at every tip are identical apart from the removed
ones; no removed path and no removed file version is left; the scanner finds no
credential; every remaining commit keeps its author, committer, dates and
message; and the commits that disappeared changed nothing but removed files.

Rehearsal on a mirror clone of GitHub, 2026-10-13:

| | Before | After |
|---|---|---|
| Branches / tags | 29 / 16 | 29 / 16 (all 45 ids changed) |
| Commits | 249 | 247 (the 2 missing changed only env files) |
| Merge commits | 24 | 24 |
| Annotated tags with tagger, date, message intact | 11 | 11 |
| Removed file versions still stored | 34 | 0 |
| Credentials found by the scanner | 2 | 0 |
| `git log --all -- <the six env paths>` | 24 commits | empty |

All verification checks passed. The 20 commits that carry a signature (merges
made on GitHub) lose it: a rewritten commit cannot keep the signature of the
original, so GitHub will no longer show them as "Verified".

### Publish (overwrites GitHub; needs the owner's explicit decision)

Not run by any script in this repository.

```bash
cd phylo-framework-mirror.git
git remote add origin git@github.com:Kiana8181/phylo-framework.git
git push --force origin 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
```

- Not `git push --mirror`: it would also try to overwrite `refs/pull/*`, which
  GitHub does not allow.
- Branch protection must permit a forced push for the moment, and be restored
  afterwards.
- Keep `phylo-framework-original.git` until everything below is finished. It is
  the only complete copy of the old history, and for that reason must itself be
  deleted at the end.
- `phylo-framework-mirror.git/filter-repo/commit-map` translates old commit ids
  into new ones (for links in issues, notes or papers).

### After publishing

- The old commits stay retrievable on GitHub by their id, through the
  pull-request refs and GitHub's caches, until GitHub removes them. Ask GitHub
  Support to remove cached views and unreachable objects for the repository,
  and name the pull requests concerned.
- Forks and existing clones keep the old history. Section 5.
- Run `python3 scripts/scan_secrets.py --history` in a fresh clone: it must
  report nothing.

---

## 5. Replacing every clone

A clone made before the rewrite must not be pulled, merged or rebased onto the
new history: that would bring the removed files straight back with the next
push. Replace it.

**Developers**

```bash
cd phylo-framework
git status                                  # anything not pushed?
git format-patch origin/<branch> -o ../my-patches    # only if you have commits that are not on GitHub
cp .env ../phylo-framework.env.backup       # your local configuration
cd .. && mv phylo-framework phylo-framework.old
git clone git@github.com:Kiana8181/phylo-framework.git
cp phylo-framework.env.backup phylo-framework/.env
cd phylo-framework && git am ../my-patches/*.patch   # only if you made patches
rm -rf ../phylo-framework.old               # it still contains the old history
```

**The server**

The data is not in the checkout: the database and the object store live in the
named volumes `phylo_postgres_data` and `phylo_minio_data`, which a new clone
in a directory of the same name uses again.

```bash
cd /path/to/phylo-framework
cp .env ~/phylo-framework.env.backup && chmod 600 ~/phylo-framework.env.backup     # first, always
./run.sh down                               # stops the containers, keeps the volumes
cd .. && mv phylo-framework phylo-framework.old
git clone git@github.com:Kiana8181/phylo-framework.git phylo-framework
cp ~/phylo-framework.env.backup phylo-framework/.env && chmod 600 phylo-framework/.env
[ -d phylo-framework.old/runtime ] && mv phylo-framework.old/runtime phylo-framework/runtime
cd phylo-framework
./run.sh check && ./run.sh prod && ./run.sh status
```

Only when `./run.sh status` reports a complete deployment and a test run has
finished: `rm -rf ../phylo-framework.old` and `rm ~/phylo-framework.env.backup`.

---

## 6. Leftovers on a developer machine

A local repository keeps more than its branches. In the working repository the
scan also found credentials in:

- `git stash` entries (listed in section 1). Look at one with
  `git stash show -p 'stash@{N}' -- . ':!.env'` (which leaves the env file
  out), keep what you need, then `git stash drop 'stash@{N}'`;
- the reflog and branches that were never pushed. Replacing the clone as in
  section 5 removes all of it at once.

Nothing here was dropped or deleted for you.

---

## 7. Keeping it clean

- `.env` files are ignored everywhere; `.env.example` holds placeholders only
  and is the one env file in the repository.
- `python3 scripts/scan_secrets.py` runs in CI and in the test suite and fails
  on a tracked env file, key file or credential.
- A line that must contain something credential-shaped on purpose (a test
  fixture) carries the marker `scan-secrets: fake`.
- The production start-up check refuses the example secrets, so a deployment
  cannot run on values that are published in `.env.example`.
