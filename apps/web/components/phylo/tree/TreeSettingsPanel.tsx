"use client";

import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import TreeOverlay from "./TreeOverlay";

function ToggleRow({
  label,
  hint,
  checked,
  onCheckedChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 py-1">
      <span className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} aria-label={label} />
    </label>
  );
}

/** Display settings for the tree renderers, shown in a right-side drawer. */
export default function TreeSettingsPanel({
  open,
  onClose,
  showLabels,
  setShowLabels,
  showInternalControls,
  showInternalNodes,
  setShowInternalNodes,
  showNodeNumbers,
  setShowNodeNumbers,
  displayFields,
  displayIdField,
  setDisplayIdField,
}: {
  open: boolean;
  onClose: () => void;
  showLabels: boolean;
  setShowLabels: (v: boolean) => void;
  showInternalControls: boolean;
  showInternalNodes: boolean;
  setShowInternalNodes: (v: boolean) => void;
  showNodeNumbers: boolean;
  setShowNodeNumbers: (v: boolean) => void;
  displayFields: string[];
  displayIdField: string;
  setDisplayIdField: (v: string) => void;
}) {
  return (
    <TreeOverlay
      open={open}
      onClose={onClose}
      side="right"
      mode="contained"
      title="Display settings"
      description="Control how the tree is drawn."
    >
      <div className="space-y-5">
        <div className="space-y-1">
          <ToggleRow
            label="Show labels"
            hint="Tip / display labels on the tree"
            checked={showLabels}
            onCheckedChange={setShowLabels}
          />
          {showInternalControls && (
            <>
              <ToggleRow
                label="Internal nodes"
                hint="Reconstructed internal node labels"
                checked={showInternalNodes}
                onCheckedChange={setShowInternalNodes}
              />
              <ToggleRow
                label="Node numbers"
                hint="Dowser/ape node index numbers"
                checked={showNodeNumbers}
                onCheckedChange={setShowNodeNumbers}
              />
            </>
          )}
        </div>

        {displayFields.length > 0 && (
          <div className="space-y-1.5">
            <label className="block text-sm font-medium">Display ID</label>
            <Select value={displayIdField} onValueChange={setDisplayIdField}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Display field" />
              </SelectTrigger>
              <SelectContent>
                {displayFields.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="space-y-1.5">
          <label className="block text-sm font-medium">Tip size by</label>
          <p className="text-sm text-muted-foreground">abundance</p>
        </div>
      </div>
    </TreeOverlay>
  );
}
