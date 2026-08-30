import type { VersionInfo } from "@phylo/contracts";
import Facts, { type Fact } from "./Facts";

/** Short git commits read better than 40-character ones; the full value stays
 *  in the stored result for anyone who needs it. */
function shortCommit(value: string | null | undefined): string | null {
  if (typeof value !== "string" || !value) return null;
  return /^[0-9a-f]{12,}$/i.test(value) ? value.slice(0, 12) : value;
}

function entries(record: Record<string, string> | undefined): Fact[] {
  if (!record) return [];
  return Object.entries(record).map(([label, value]) => ({ label, value }));
}

/**
 * Environment identity behind a run: framework build, service image, and the
 * tool versions pinned by the build definition.
 *
 * Renders nothing when the run carries no `version_info` — runs recorded before
 * environment capture existed are still readable, they simply show no section.
 */
export default function VersionInfoSection({ versionInfo }: { versionInfo?: VersionInfo }) {
  if (!versionInfo) return null;

  const { framework, service, service_reported: reported, unavailable } = versionInfo;

  const frameworkFacts: Fact[] = [
    { label: "Framework", value: framework?.version },
    { label: "Commit", value: shortCommit(framework?.git_commit) },
    { label: "Branch", value: framework?.git_branch },
    // Only worth surfacing when true: a clean tree is the unremarkable case.
    { label: "Working tree", value: framework?.git_dirty ? "modified" : null },
    { label: "Captured", value: versionInfo.captured_at },
  ];

  const serviceFacts: Fact[] = [
    { label: "Image", value: service?.image_name },
    { label: "Image digest", value: service?.image_digest },
    { label: "Base image", value: service?.base_image },
    ...entries(service?.build_args),
    ...entries(service?.tool_versions),
  ];

  const reportedFacts: Fact[] = reported
    ? Object.entries(reported).flatMap(([group, value]) => {
        if (!value || typeof value !== "object") {
          return [{ label: group, value: value as string | number | null }];
        }
        return Object.entries(value as Record<string, unknown>).map(([key, inner]) => ({
          label: `${group}.${key}`,
          // `version_raw` values are multi-line; collapse them for the grid.
          value:
            inner == null ? null : String(inner).replace(/\s+/g, " ").trim().slice(0, 120),
        }));
      })
    : [];

  const missing = Object.entries(unavailable ?? {});

  const hasAnything =
    frameworkFacts.some((f) => f.value != null && f.value !== "") ||
    serviceFacts.some((f) => f.value != null && f.value !== "") ||
    reportedFacts.length > 0 ||
    missing.length > 0;
  if (!hasAnything) return null;

  return (
    <details className="rounded border bg-card/50 p-3">
      <summary className="cursor-pointer text-sm font-medium">
        Show environment &amp; versions
      </summary>

      <div className="mt-3 space-y-4">
        <Facts facts={frameworkFacts} />

        {serviceFacts.some((f) => f.value != null && f.value !== "") && (
          <div className="space-y-2 border-t pt-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {versionInfo.method_id ?? "Method"} service
            </p>
            <Facts facts={serviceFacts} />
          </div>
        )}

        {reportedFacts.length > 0 && (
          <div className="space-y-2 border-t pt-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Reported by the service at run time
            </p>
            <Facts facts={reportedFacts} />
          </div>
        )}

        {missing.length > 0 && (
          <div className="space-y-1 border-t pt-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Not recorded
            </p>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {missing.map(([field, reason]) => (
                <li key={field}>
                  <code className="break-all">{field}</code> — {reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
