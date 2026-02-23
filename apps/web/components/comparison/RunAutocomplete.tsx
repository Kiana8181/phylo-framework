"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type RunAutocompleteOption = {
  id: string;
  method_id: string;
};

type RunAutocompleteProps = {
  value: string | null;
  onChange: (newRunId: string | null) => void;
  options: RunAutocompleteOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
};

type RankedOption = {
  option: RunAutocompleteOption;
  rank: number;
};

const PREFIX_LEN = 8;

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

export function formatRunLabel(option: RunAutocompleteOption): string {
  return `${option.method_id} · ${option.id.slice(0, PREFIX_LEN)}…`;
}

export function filterRunOptions(options: RunAutocompleteOption[], query: string): RunAutocompleteOption[] {
  const q = normalize(query);
  if (!q) return options;

  const ranked: RankedOption[] = [];
  for (const option of options) {
    const id = normalize(option.id);
    const idPrefix = id.slice(0, PREFIX_LEN);
    const method = normalize(option.method_id);
    const fields = [id, idPrefix, method];

    const exact = fields.some((field) => field === q);
    const startsWith = fields.some((field) => field.startsWith(q));
    const contains = fields.some((field) => field.includes(q));

    if (!contains) continue;

    const rank = exact ? 0 : startsWith ? 1 : 2;
    ranked.push({ option, rank });
  }

  return ranked
    .sort((a, b) => {
      if (a.rank !== b.rank) return a.rank - b.rank;
      const methodCompare = a.option.method_id.localeCompare(b.option.method_id, "en");
      if (methodCompare !== 0) return methodCompare;
      return a.option.id.localeCompare(b.option.id, "en");
    })
    .map((item) => item.option);
}

export default function RunAutocomplete({
  value,
  onChange,
  options,
  placeholder = "Select run…",
  disabled = false,
  className,
}: RunAutocompleteProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const selectedOption = useMemo(
    () => (value ? options.find((option) => option.id === value) ?? null : null),
    [options, value],
  );

  const filteredOptions = useMemo(() => filterRunOptions(options, query), [options, query]);

  const close = useCallback(() => {
    setOpen(false);
    setActiveIndex(0);
    setQuery(value ?? "");
  }, [value]);

  const selectOption = useCallback(
    (option: RunAutocompleteOption | null) => {
      onChange(option?.id ?? null);
      setQuery(option?.id ?? "");
      setOpen(false);
      setActiveIndex(0);
    },
    [onChange],
  );

  useEffect(() => {
    if (open) return;
    setQuery(value ?? "");
  }, [open, value]);

  useEffect(() => {
    setActiveIndex((prev) => {
      if (!filteredOptions.length) return 0;
      return Math.min(prev, filteredOptions.length - 1);
    });
  }, [filteredOptions.length]);

  useEffect(() => {
    if (!open) return;
    const onDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (!rootRef.current?.contains(target)) {
        close();
      }
    };
    document.addEventListener("mousedown", onDocumentMouseDown);
    return () => document.removeEventListener("mousedown", onDocumentMouseDown);
  }, [close, open]);

  const displayValue = open ? query : selectedOption ? formatRunLabel(selectedOption) : "";

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <div className="relative">
        <Input
          value={displayValue}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={() => {
            setQuery(value ?? "");
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            if (!open) setOpen(true);
          }}
          onPaste={(event) => {
            const pasted = event.clipboardData.getData("text").trim();
            if (!pasted) return;
            const exactMatch = options.find((option) => option.id === pasted);
            if (exactMatch) {
              event.preventDefault();
              selectOption(exactMatch);
              const input = rootRef.current?.querySelector("input");
              input?.blur();
              return;
            }
            if (!open) setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              if (!open) {
                setOpen(true);
                return;
              }
              if (!filteredOptions.length) return;
              setActiveIndex((prev) => Math.min(prev + 1, filteredOptions.length - 1));
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              if (!open) {
                setOpen(true);
                return;
              }
              if (!filteredOptions.length) return;
              setActiveIndex((prev) => Math.max(prev - 1, 0));
              return;
            }
            if (event.key === "Enter" && open) {
              event.preventDefault();
              if (!filteredOptions.length) return;
              selectOption(filteredOptions[activeIndex] ?? null);
              const input = rootRef.current?.querySelector("input");
              input?.blur();
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              close();
              const input = rootRef.current?.querySelector("input");
              input?.blur();
            }
          }}
          className="w-full pr-14 font-mono text-sm"
        />
        <div className="pointer-events-none absolute right-10 top-1/2 -translate-y-1/2 text-muted-foreground">
          <ChevronsUpDown className="h-4 w-4" />
        </div>
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2"
            onClick={() => selectOption(null)}
            aria-label="Clear selected run"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {open && (
        <div className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border bg-background p-1 shadow-lg">
          {filteredOptions.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-muted-foreground">No runs found.</div>
          ) : (
            filteredOptions.map((option, index) => {
              const selected = value === option.id;
              const active = index === activeIndex;
              return (
                <button
                  key={option.id}
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    selectOption(option);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm",
                    active && "bg-muted",
                    selected && "font-medium",
                  )}
                >
                  <span className="shrink-0 text-muted-foreground">
                    <Check className={cn("h-4 w-4", selected ? "opacity-100" : "opacity-0")} />
                  </span>
                  <span className="truncate">{formatRunLabel(option)}</span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
