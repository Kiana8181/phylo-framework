"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  type ContractSpec,
  type FormattedParamValue,
  type ResolvedParam,
  type ResolvedRunParams,
} from "@/features/runs/params";

const DEFAULT_GROUP_ID = "__default";
const UNKNOWN_GROUP_ID = "__unknown";

type ParamGroup = {
  id: string;
  label: string;
  items: ResolvedParam[];
};

export function ParamValue({
  formatted,
  dense,
}: {
  formatted: FormattedParamValue;
  dense: boolean;
}) {
  if (formatted.kind === "chips") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {formatted.chips.map((chip, idx) => (
          <span
            key={`${chip}-${idx}`}
            className={cn(
              "rounded-full border bg-muted/40 px-2 py-0.5 text-xs break-all",
              dense && "text-[11px]",
            )}
          >
            {chip}
          </span>
        ))}
      </div>
    );
  }

  if (formatted.kind === "json") {
    return (
      <details className="rounded border bg-card/40 p-2">
        <summary className="cursor-pointer text-[11px] font-medium">Show JSON value</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words text-[11px]">{formatted.json}</pre>
      </details>
    );
  }

  return <p className={cn("text-xs break-words", dense && "text-[11px]")}>{formatted.text}</p>;
}

function buildGroups(spec: ContractSpec | undefined | null, knownItems: ResolvedParam[]): ParamGroup[] {
  const byId = new Map<string, ParamGroup>();
  const order: string[] = [];

  (spec?.sections ?? []).forEach((section) => {
    byId.set(section.id, { id: section.id, label: section.label, items: [] });
    order.push(section.id);
  });

  knownItems.forEach((item) => {
    const groupId = item.section || DEFAULT_GROUP_ID;
    if (!byId.has(groupId)) {
      byId.set(groupId, { id: groupId, label: item.section || "Parameters", items: [] });
      order.push(groupId);
    }
    byId.get(groupId)?.items.push(item);
  });

  return order
    .map((groupId) => byId.get(groupId))
    .filter((group): group is ParamGroup => Boolean(group && group.items.length > 0));
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-xs break-words">{value}</p>
    </div>
  );
}

/**
 * Shared presentational body for run parameters: a meta grid plus the grouped
 * parameter list. Reused by the compact dropdown and the inline Run Summary
 * panel so both stay in sync. Callers render their own action footer.
 */
export default function RunParamsContent({
  methodKey,
  contractSpec,
  runId,
  resolved,
  datasetLabel,
  sameDatasetLabel,
  dense = false,
  listOpen,
}: {
  methodKey: string;
  contractSpec?: ContractSpec | null;
  runId?: string;
  resolved: ResolvedRunParams;
  datasetLabel: string;
  sameDatasetLabel?: string;
  dense?: boolean;
  /** Whether the inner "parameter list" details starts expanded. */
  listOpen?: boolean;
}) {
  const groups = useMemo(
    () => buildGroups(contractSpec, resolved.known),
    [contractSpec, resolved.known],
  );

  return (
    <div className="space-y-3">
      <div className="rounded-lg border bg-card/50 p-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <MetaRow label="Run ID" value={runId ?? "—"} />
          <MetaRow label="Method" value={contractSpec?.methodLabel || methodKey} />
          <MetaRow label="Dataset" value={datasetLabel} />
          {sameDatasetLabel !== undefined && (
            <MetaRow label="Same Datasets" value={sameDatasetLabel} />
          )}
        </div>
      </div>

      {resolved.setCount === 0 ? (
        <p className="rounded-lg border bg-card/40 p-3 text-sm text-muted-foreground">
          No parameters were set for this run.
        </p>
      ) : (
        <details className="overflow-x-auto rounded border bg-card/50 p-3" open={listOpen ?? !dense}>
          <summary className="cursor-pointer text-sm font-medium">Show parameter list</summary>
          <div className="mt-2 space-y-3">
            {groups.map((group) => (
              <div key={group.id} className="space-y-2">
                {group.id !== DEFAULT_GROUP_ID && (
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </p>
                )}
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {group.items.map((item) => (
                    <div key={item.key} className="rounded-lg border bg-background/70 p-2">
                      <p className="text-xs font-medium">{item.label}</p>
                      {item.description && (
                        <p className="mt-0.5 text-[11px] text-muted-foreground">{item.description}</p>
                      )}
                      <div className="mt-1.5">
                        <ParamValue formatted={item.formatted} dense={dense} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {resolved.unknown.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Other / Unknown
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {resolved.unknown.map((item) => (
                    <div key={`${UNKNOWN_GROUP_ID}-${item.key}`} className="rounded-lg border bg-background/70 p-2">
                      <p className="text-xs font-medium">{item.key}</p>
                      <div className="mt-1.5">
                        <ParamValue formatted={item.formatted} dense={dense} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
