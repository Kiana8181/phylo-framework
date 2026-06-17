"use client";

import { useEffect, useRef, useState } from "react";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { useMethods } from "@/features/methods/hooks";
import type { RunListFilters } from "@/features/runs/api";

const STATUSES = ["PENDING", "QUEUED", "RUNNING", "DONE", "ERROR", "CANCELLED"] as const;
const ALL = "__all";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}

export default function RunHistoryFilters({
  value,
  onChange,
}: {
  value: RunListFilters;
  onChange: (next: RunListFilters) => void;
}) {
  const { data: methods } = useMethods();
  const [runIdInput, setRunIdInput] = useState(value.runId ?? "");
  const [datasetInput, setDatasetInput] = useState(value.dataset ?? "");

  // Read latest props inside the debounce without making them effect deps.
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };

  // Debounce the free-text fields before hitting the backend.
  useEffect(() => {
    const id = setTimeout(() => {
      const { value: v, onChange: cb } = latest.current;
      const next = runIdInput.trim() || undefined;
      if ((v.runId ?? undefined) !== next) cb({ ...v, runId: next });
    }, 300);
    return () => clearTimeout(id);
  }, [runIdInput]);

  useEffect(() => {
    const id = setTimeout(() => {
      const { value: v, onChange: cb } = latest.current;
      const next = datasetInput.trim() || undefined;
      if ((v.dataset ?? undefined) !== next) cb({ ...v, dataset: next });
    }, 300);
    return () => clearTimeout(id);
  }, [datasetInput]);

  // Keep inputs in sync when filters are cleared/changed externally.
  useEffect(() => setRunIdInput(value.runId ?? ""), [value.runId]);
  useEffect(() => setDatasetInput(value.dataset ?? ""), [value.dataset]);

  const hasActive = !!(
    value.runId ||
    value.dataset ||
    value.status ||
    value.methodId ||
    value.createdOn
  );

  const clear = () => {
    setRunIdInput("");
    setDatasetInput("");
    onChange({});
  };

  return (
    <div className="mb-5 rounded-xl border bg-card/40 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <SlidersHorizontal className="size-4 text-muted-foreground" />
          Filters
        </div>
        {hasActive && (
          <Button variant="ghost" size="sm" onClick={clear} className="h-7 gap-1.5 px-2 text-xs">
            <X className="size-3.5" />
            Clear all
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <Field label="Run ID">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={runIdInput}
              onChange={(e) => setRunIdInput(e.target.value)}
              placeholder="Search run ID…"
              className="pl-8"
            />
          </div>
        </Field>

        <Field label="Dataset">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={datasetInput}
              onChange={(e) => setDatasetInput(e.target.value)}
              placeholder="Search dataset…"
              className="pl-8"
            />
          </div>
        </Field>

        <Field label="Status">
          <Select
            value={value.status ?? ALL}
            onValueChange={(v) => onChange({ ...value, status: v === ALL ? undefined : v })}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Method">
          <Select
            value={value.methodId ?? ALL}
            onValueChange={(v) => onChange({ ...value, methodId: v === ALL ? undefined : v })}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="All methods" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All methods</SelectItem>
              {(methods ?? []).map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.name || m.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Created">
          <Input
            type="date"
            value={value.createdOn ?? ""}
            onChange={(e) => onChange({ ...value, createdOn: e.target.value || undefined })}
          />
        </Field>
      </div>
    </div>
  );
}
