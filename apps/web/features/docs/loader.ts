// Build-time loader: imports each method's contracts JSON (the very files the
// API serves and the FormBuilder renders) and assembles them into LoadedMethod
// objects. No backend/auth dependency — fully static, no drift from the form.

import { acceptsToFormats, type InputFormat } from "@/lib/fileTypes";
import { buildMethodDocModel, type LoadedMethod } from "./model";
import { getMethodContent } from "./content";
import type { MethodDocModel, MethodId } from "./types";

import dowserSpec from "@phylo/contracts/methods/dowser/spec.json";
import dowserParams from "@phylo/contracts/methods/dowser/param.schema.json";
import dowserUi from "@phylo/contracts/methods/dowser/ui.json";

import gctreeSpec from "@phylo/contracts/methods/gctree/spec.json";
import gctreeParams from "@phylo/contracts/methods/gctree/param.schema.json";
import gctreeUi from "@phylo/contracts/methods/gctree/ui.json";

import brepphyloSpec from "@phylo/contracts/methods/brepphylo/spec.json";
import brepphyloParams from "@phylo/contracts/methods/brepphylo/param.schema.json";
import brepphyloUi from "@phylo/contracts/methods/brepphylo/ui.json";

import clonaltreeSpec from "@phylo/contracts/methods/clonaltree/spec.json";
import clonaltreeParams from "@phylo/contracts/methods/clonaltree/param.schema.json";
import clonaltreeUi from "@phylo/contracts/methods/clonaltree/ui.json";

type RawSpec = { name?: string; accepts?: string[] };

const FORMAT_LABELS: Record<Exclude<InputFormat, "unknown">, string> = {
  fasta: "FASTA",
  csv: "CSV",
  tsv: "TSV",
  zip: "ZIP",
  rda: "RDA",
  rds: "RDS",
};

function friendlyFormats(accepts: string[] | undefined): string[] {
  return [...acceptsToFormats(accepts)]
    .filter((f): f is Exclude<InputFormat, "unknown"> => f !== "unknown")
    .map((f) => FORMAT_LABELS[f]);
}

type RawBundle = { spec: unknown; params: unknown; ui: unknown };

const RAW: Record<MethodId, RawBundle> = {
  dowser: { spec: dowserSpec, params: dowserParams, ui: dowserUi },
  gctree: { spec: gctreeSpec, params: gctreeParams, ui: gctreeUi },
  brepphylo: { spec: brepphyloSpec, params: brepphyloParams, ui: brepphyloUi },
  clonaltree: { spec: clonaltreeSpec, params: clonaltreeParams, ui: clonaltreeUi },
};

function loadMethod(id: MethodId): LoadedMethod {
  const { spec, params, ui } = RAW[id];
  const rawSpec = spec as RawSpec;
  return {
    id,
    name: rawSpec.name ?? getMethodContent(id).displayName,
    acceptFormats: friendlyFormats(rawSpec.accepts),
    paramSchema: params as LoadedMethod["paramSchema"],
    uiHints: ui as LoadedMethod["uiHints"],
  };
}

/** Auto-generated field-table model for a method, merged with its authored overlay. */
export function getMethodDocModel(id: MethodId): MethodDocModel {
  return buildMethodDocModel(loadMethod(id), getMethodContent(id));
}

/**
 * The raw loaded contracts (paramSchema + uiHints) for a method. Exposed so the
 * cross-method compatibility model can classify columns directly from the same
 * JSON the form and per-method docs consume — no drift, no second source.
 */
export function getLoadedMethod(id: MethodId): LoadedMethod {
  return loadMethod(id);
}
