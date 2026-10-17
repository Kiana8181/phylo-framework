# Object storage: replacing the unmaintained MinIO image

Investigated 2026-10-12. **Status: adopted.** `docker-compose.yml` and
`docker-compose.test.yml` now use the Silo images pinned by digest. One step of
the recommendation is still open: mirroring the images into a registry the
group controls (see "How to adopt it safely", step 3, and
[DEPLOYMENT.md](./DEPLOYMENT.md#object-store-image)).

After the switch, on a throwaway copy of the production profile: data written
by the old MinIO image was read back through Silo with matching sizes and
checksums, the existing account and the write-only methods policy kept working,
one new run per method completed with artifacts, and the storage integration
tests (10) and scientific end-to-end tests (8) passed.

## Why this is needed

- Upstream MinIO stopped publishing Community Edition images in October 2025.
  The last open-source release is `RELEASE.2025-10-15`; the `minio/minio` and
  `minio/mc` GitHub repositories are archived (read-only).
- Verified on 2026-10-12: `minio/minio` and `minio/mc` cannot be pulled from
  Docker Hub (repository not found), `quay.io` (no manifest) or `ghcr.io`
  (denied). `bitnami/minio` is also gone; `bitnamilegacy/minio` is a frozen
  archive, not a maintained image.
- The image this project pins is a September 2025 build. Trivy reports 9
  critical and 112 high findings in it, and it will never receive a fix.

A cached copy of that image is therefore not a solution: it cannot be
re-downloaded and it cannot be patched.

## Recommendation

**Adopt Silo (`pgsty/silo`), the maintained community fork of MinIO, pinned by
digest, and mirror the pinned images into a registry the group controls.**

It is the only option that needs no code change, no configuration change and
no data migration, and it is the only candidate where every one of the
project's storage tests was actually run and passed. Keep SeaweedFS as the
documented fallback if the fork stops being maintained.

The trade-off to accept knowingly: Silo is a young, single-organisation fork
(first release December 2025, one dominant maintainer). That is why the
recommendation includes a mirror and a re-check, not just an image swap.

## What was verified for Silo

### Provenance

| Check | Result |
|---|---|
| Source | `github.com/pgsty/silo`, a GitHub fork of `minio/minio`, AGPL-3.0 (same licence as MinIO) |
| Activity | Not archived; last push 2026-10-08; 11 releases between 2025-12-15 and 2026-09-16 |
| Image → source | Image label `org.opencontainers.image.revision` is commit `2a4d51406b7e`; that commit exists in the repository, dated the day of the release tag `RELEASE.2026-09-16T00-00-00Z`. The binary reports the same commit id |
| Platforms | `linux/amd64` and `linux/arm64`, each with a build attestation manifest |
| Security handling | Has a `SECURITY.md` and an advisory ledger; release notes reference fixed CVEs (10 in the June 2026 release, 10 in April 2026) |
| Not verified | Commits are not signature-verified; images are not cosign-signed; the build pipeline itself was not audited; the fork has no published GitHub security advisories of its own |

### Scan results (Trivy 0.75.0, all severities)

| Image | Critical | High | Medium | Low | Notes |
|---|---|---|---|---|---|
| Current `minio/minio` (pinned digest) | 9 | 112 | 137 | 24 | Never patched again |
| `pgsty/silo:RELEASE.2026-09-16T00-00-00Z-distroless` | 0 | 5 | 7 | 1 | See below |
| `pgsty/silo:RELEASE.2026-09-16T00-00-00Z` (UBI base) | 0 | 15 | 52 | 15 | Larger base image; 6 unfixed `pcre2` findings |
| Current `minio/mc` (pinned digest) | 2 | 51 | 97 | 20 | |
| `pgsty/mc:RELEASE.2026-09-16T00-00-00Z` | 0 | 10 | 45 | 14 | One-shot init container only |

The five high findings in the distroless image:

- Three in the Go standard library and one in `golang.org/x/net` (HTTP/2,
  HTTP Range and TLS denial-of-service). They were published after the
  September release and are fixed by a rebuild with Go 1.27.2. They affect any
  Go program built at that time; SeaweedFS's current release has the same
  four.
- One reported against `github.com/minio/minio` (CVE-2026-39414, memory
  exhaustion in S3 Select CSV parsing). The fork fixed this in commit
  `c5765dcbb` (April 2026, issue 25). The scanner still reports it because
  the fork keeps MinIO's Go module path. This project does not use S3 Select.

The scanner can read the full dependency list of this binary (261 Go modules),
so these numbers reflect the real contents of the image.

### Compatibility, tested on throwaway volumes

| Test | Result |
|---|---|
| Start the fork on a data volume written by the current MinIO | Started; no migration step |
| Objects written by MinIO (1.5 KB, 300 KB, 12 MB) read back through the fork | SHA-256 identical, metadata intact |
| Buckets, the `phylo-methods-write` policy and the methods user carried over | Yes, before re-running any init step |
| Write-only methods user: put to artifacts allowed; put to datasets, get, list, delete all denied | Identical behaviour before and after the switch |
| The real `minio-init` script from `docker-compose.yml`, run with `pgsty/mc` | Exit 0, idempotent |
| Rollback: current MinIO started again on the volume the fork had written to | Started; objects intact; policy enforced |
| `tests/integration` (storage contract: upload, download, stream, move, presigned URL, delete) | 10 passed |
| `tests/e2e` (all four methods, API → worker → method → store → download) | 8 passed; 19 artifacts stored, including uploads from the R services |

Environment variables (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`), the
`server /data --console-address` command, the `mc admin` commands and the S3
endpoint are all unchanged.

### How to adopt it safely

1. Back up first (database dump plus a copy of the MinIO volume, as in
   `DEPLOYMENT.md`). The in-place switch was reversible in testing, but that is
   a test result, not a guarantee.
2. Change three image references to the pinned multi-architecture digests:

   | Service | New image |
   |---|---|
   | `minio` (`docker-compose.yml`) | `pgsty/silo@sha256:32a8a777d90f3296294c9a57da5e8d397121187c4b868b2a7fc7874c726c0291` |
   | `minio-init` (`docker-compose.yml`) | `pgsty/mc@sha256:cfc83108c3abb371f8fb84d99c1fdc88f8c237e022409b0081fb7c0a3be634dd` |
   | `minio` (`docker-compose.test.yml`) | the same `pgsty/silo` digest |

   No other file changes. The existing data volume is reused as it is.
3. Mirror both images into a registry the group controls (for example the
   project's GitHub Container Registry) and pull from there. This is what
   protects against the fork's Docker Hub repository disappearing the way
   MinIO's did; a local image cache does not.
4. Add both images to the scheduled image scan (Phase 3) so a stale or newly
   vulnerable pin is noticed.
5. Re-check the fork's health every few months: last commit, last release, and
   whether Go-toolchain CVEs are being picked up. If it goes quiet, move to the
   fallback below.

The distroless variant has no shell. That is fine here: the service has no
container healthcheck, and `minio-init` already waits for it from outside.

## Alternatives evaluated

All four are actively maintained and pullable. The first two were run against
the project's own storage contract test; the write-only methods user was
tested by hand.

| | Silo (recommended) | RustFS 1.0.1 | SeaweedFS 4.48 | Garage v2.4.1 |
|---|---|---|---|---|
| Licence | AGPL-3.0 | Apache-2.0 | Apache-2.0 | AGPL-3.0 |
| Maturity | MinIO code base; fork since Dec 2025 | First stable release Sept 2026 | Years of production use; near-weekly releases | Stable; built for small clusters |
| Storage contract test (6 cases) | Passed | Passed | Passed | Not run |
| Presigned URLs | Yes | Yes | Yes | Yes (documented) |
| Write-only methods user | Yes, unchanged | Yes, with the same `mc admin` commands | **No**: its `Write` permission also allows delete | **No**: per-key permissions are read / write / owner only |
| Reuse existing credentials | Yes | Yes | Yes | **No**: access keys must use Garage's own `GK…` format |
| `minio-init` service | Unchanged | Works with `mc` | Replace with a static identity file | Replace with `garage` CLI steps |
| Existing data | Used in place | Must be copied | Must be copied | Must be copied |
| Code changes | None | None | None (`STORAGE_BACKEND=s3`) | None in the app; new init and config |
| Scan result | 0 critical / 5 high (real) | 0 / 0, **but the scanner could not inspect the Rust binary** | 0 critical / 4 high (real) | No findings, **scanner found nothing it could inspect** |
| Memory at idle | not measured | not measured | about 90 MB | not measured |

Notes:

- **RustFS** is the closest drop-in after Silo and passed everything that was
  tried. It is not recommended as the first choice because 1.0 is a month old
  and because its clean scan is not evidence: Trivy saw only the 35 Alpine
  packages and could not see the Rust dependencies compiled into the binary.
- **SeaweedFS** is the most mature alternative and the right fallback. Its one
  functional gap for this project is the methods user: a method container
  could delete artifacts, not only add them. That weakens one isolation layer
  and would need compensating controls.
- **Garage** fits small deployments well but needs the most rework here
  (credentials, init, permissions) and has the coarsest permission model.
- **Versity Gateway** and **Ceph RGW** were not tested. The first is a gateway
  in front of a filesystem with a different permission model; the second is far
  heavier than a single shared server warrants.
- **Building MinIO from the archived source** would reproduce the unpatched
  code; it only solves availability, not security.

For any alternative other than Silo, data migration is an object copy
(`mc mirror` from the old store to the new one, both running), followed by a
check of object counts and a spot check of checksums. Database rows store
bucket names and object keys, not server addresses, so they do not change as
long as bucket names and keys are kept.

## Sources

Primary: GitHub repository metadata and release lists for `minio/minio`,
`minio/mc`, `pgsty/silo`, `rustfs/rustfs`, `seaweedfs/seaweedfs`,
`versity/versitygw`, and the Garage release list; registry manifest queries;
local Trivy scans; local test runs.

Background reading:

- [MinIO Docker Images: Recent Changes](https://www.chainguard.dev/unchained/secure-and-free-minio-chainguard-containers)
- [MinIO Nuked Its Docker Hub Repos](https://vonng.com/en/db/silo-is-coming/) (written by the Silo maintainer)
- [MinIO CE in 2026: Retired Upstream, Source-Only](https://www.glukhov.org/data-infrastructure/object-storage/minio-dead/)
- [MinIO Ends Active Development](https://linuxiac.com/minio-ends-active-development/)
- [SeaweedFS vs Garage vs Ceph 2026](https://akmatori.com/blog/minio-alternatives-2026-comparison)
- [MinIO Alternatives Compared: RustFS, SeaweedFS, and Garage](https://lowcloud.io/en/blog/minio-alternatives)
