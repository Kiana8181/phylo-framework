/** The dataset chosen in Step 2: either a freshly picked local file to upload,
 *  or an already-uploaded dataset referenced by its file id. */
export type ChosenInput =
  | { kind: "upload"; file: File }
  | {
      kind: "existing";
      fileId: string;
      display: { name: string; size: number };
      mimeType?: string | null;
    };

export function chosenInputName(input: ChosenInput): string {
  return input.kind === "upload" ? input.file.name : input.display.name;
}

export function chosenInputMime(input: ChosenInput): string | null | undefined {
  return input.kind === "upload" ? input.file.type : input.mimeType;
}
