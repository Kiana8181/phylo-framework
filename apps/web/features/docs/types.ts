// Types for the auto-generated method documentation models.
// Field metadata is derived programmatically from each method's
// param.schema.json + ui.json (the same files that drive the live form),
// then merged with the authored content overlay in `content.ts`.

export type MethodId = "dowser" | "gctree" | "brepphylo" | "clonaltree";

export const METHOD_IDS: MethodId[] = ["dowser", "gctree", "brepphylo", "clonaltree"];

/** A single documented form field (auto-generated, mapping merged from overlay). */
export type DocField = {
  /** Field path as used by the form, e.g. "tree_build" or "column_map.sequence_id". */
  name: string;
  label: string;
  description?: string;
  /** Human-readable allowed values, e.g. "pratchet, pml, dnapars …" or "Yes / No" or "integer (1–10)". */
  allowedValues: string;
  /** Human-readable default, "—" when empty/unset. */
  defaultValue: string;
  /** Native method parameter this maps to; "" when no clear mapping (left blank by design). */
  mapsTo: string;
  /** Human-readable conditional-visibility note, "" when always shown. */
  visibleWhen: string;
  required: boolean;
};

export type DocSection = {
  id: string;
  label: string;
  fields: DocField[];
};

export type MethodDocModel = {
  id: MethodId;
  name: string;
  /** Friendly accepted input formats derived from spec.json `accepts` (e.g. ["CSV", "TSV"]). */
  acceptFormats: string[];
  sections: DocSection[];
  /** Human-readable "field A and field B are mutually exclusive" notes (from ui.json validation). */
  mutuallyExclusive: string[];
  /** Human-readable conditional-required notes (from ui.json validation.requiredWhen). */
  conditionalRequired: string[];
};

/** One row of the authored "input types the method accepts" table. */
export type InputTypeRow = {
  type: string;
  handling: string;
  needsVerification?: boolean;
};

/** A single manifest role (mandatory or optional) within a ZIP-bundle scenario. */
export type ZipBundleRole = {
  /** The role key as written in manifest.json `files`, e.g. "aligned_fasta". */
  role: string;
  /** What this file is and how it is used. */
  description: string;
};

/** One accepted ZIP-bundle scenario (the manifest.json `scenario` value). */
export type ZipBundleScenario = {
  /** manifest.json `scenario` value, e.g. "dnapars_outfile_with_abundance". */
  scenario: string;
  /** Plain-English description of when to use this scenario. */
  when: string;
  /** Manifest roles that MUST be present for this scenario. */
  required: ZipBundleRole[];
  /** Manifest roles that may optionally be included. */
  optional: ZipBundleRole[];
};

/** Detailed spec for a method that accepts a ZIP-bundle input (e.g. GCtree). */
export type ZipBundleSpec = {
  /** Intro paragraph(s) describing why/when a ZIP is used. */
  intro: string[];
  /** Structural rules about archive layout and manifest placement. */
  layout: string[];
  /** A minimal manifest.json example, rendered verbatim in a code block. */
  manifestExample: string;
  /** Per-scenario required/optional manifest roles. */
  scenarios: ZipBundleScenario[];
  /** Notes about specific file formats (idmap, abundances, isotype map, …). */
  fileFormats?: ZipBundleRole[];
};

/** Authored content overlay for a method (conceptual; sourced from external docs + in-code descriptions). */
export type MethodContent = {
  id: MethodId;
  displayName: string;
  tagline: string;
  externalDocUrl: string;
  externalDocLabel: string;
  /** Conceptual capability summary paragraphs (from external docs). */
  summary: string[];
  capabilities: string[];
  inputTypes: InputTypeRow[];
  /** field name → native-parameter mapping text. Only the clearly-verifiable ones are filled. */
  fieldMappings: Record<string, string>;
  /** Extra authored prose about conditional behaviour, beyond the auto-generated notes. */
  conditionalNotes?: string[];
  /** Detailed ZIP-bundle format spec, for methods that accept a pre-built bundle. */
  zipBundle?: ZipBundleSpec;
};
