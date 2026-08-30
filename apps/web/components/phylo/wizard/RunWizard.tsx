"use client";

import { useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Loading } from "@/components/ui/loading";
import MethodsGrid from "@/components/phylo/MethodsGrid";
import { useMethodSpec } from "@/features/methods/hooks";
import { useCreateRun } from "@/features/runs/hooks";
import { useUploadSession } from "@/features/uploads/hooks";
import { notify } from "@/lib/notify";
import type { MethodInfo } from "@phylo/contracts";
import WizardStepper, { type WizardStepIndex } from "./WizardStepper";
import DataStep from "./DataStep";
import ParametersStep from "./ParametersStep";
import type { ChosenInput } from "./types";

type Step = 1 | 2 | 3;

export default function RunWizard({
  methods,
  onSubmitDone,
  onStartOver,
  initialMethodId,
  initialParams,
  initialFileId,
  prefillNote,
}: {
  methods: MethodInfo[];
  onSubmitDone: (runId: string) => void;
  onStartOver?: () => void;
  initialMethodId?: string | null;
  initialParams?: Record<string, unknown> | null;
  initialFileId?: string | null;
  /** Banner copy explaining where the pre-filled values came from. */
  prefillNote?: string | null;
}) {
  const initialMethod = useMemo(
    () => (initialMethodId ? (methods.find((m) => m.id === initialMethodId) ?? null) : null),
    [methods, initialMethodId],
  );
  const [step, setStep] = useState<Step>(initialMethod ? 2 : 1);
  const [selectedMethod, setSelectedMethod] = useState<MethodInfo | null>(initialMethod);
  const [chosen, setChosen] = useState<ChosenInput | null>(null);
  const [autoSelectConsumed, setAutoSelectConsumed] = useState(false);
  const [prefilled, setPrefilled] = useState(!!initialMethod);

  const { data: spec, isLoading: specLoading } = useMethodSpec(selectedMethod?.id);
  const createRun = useCreateRun();
  const uploadSession = useUploadSession();

  const selectMethod = (m: MethodInfo) => {
    if (m.id !== selectedMethod?.id) setChosen(null);
    setSelectedMethod(m);
    setStep(2);
  };

  const chooseInput = (input: ChosenInput) => {
    setAutoSelectConsumed(true);
    setChosen(input);
    setStep(3);
  };

  const startOver = () => {
    setStep(1);
    setSelectedMethod(null);
    setChosen(null);
    setAutoSelectConsumed(true);
    setPrefilled(false);
    onStartOver?.();
  };

  const usingDefaults = prefilled && selectedMethod?.id === initialMethodId;

  async function handleRun(values: Record<string, unknown>) {
    if (!selectedMethod || !chosen) return;
    try {
      let fileId: string | null = chosen.kind === "existing" ? chosen.fileId : null;
      if (chosen.kind === "upload") {
        const uploaded = await uploadSession.upload(chosen.file);
        fileId = uploaded.file_id;
      }
      const res = await createRun.mutateAsync({
        methodId: selectedMethod.id,
        params: values ?? {},
        fileId,
      });
      onSubmitDone(res.run_id);
    } catch (e: unknown) {
      if ((e as { aborted?: boolean })?.aborted) {
        notify.error("Upload cancelled", "The file upload was cancelled.");
      } else {
        notify.error("Run failed", (e as Error)?.message ?? "Unknown error");
      }
    }
  }

  return (
    <Card className="space-y-6 p-4 sm:p-6">
      {prefilled && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2.5">
          <p className="text-sm text-muted-foreground">
            {prefillNote ?? "Settings carried over — tweak anything, or start from scratch."}
          </p>
          <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={startOver}>
            <RotateCcw className="size-4" />
            Start fresh
          </Button>
        </div>
      )}

      <WizardStepper
        current={step}
        onStepClick={(target: WizardStepIndex) => {
          if (target < step) setStep(target as Step);
        }}
      />

      {step === 1 && (
        <MethodsGrid methods={methods} selectedId={selectedMethod?.id ?? null} onSelect={selectMethod} />
      )}

      {step === 2 &&
        (specLoading || !spec ? (
          <Loading label="Loading method…" />
        ) : (
          <DataStep
            spec={spec}
            autoSelectFileId={
              !autoSelectConsumed && selectedMethod?.id === initialMethodId ? (initialFileId ?? null) : null
            }
            onChoose={chooseInput}
            onBack={() => setStep(1)}
          />
        ))}

      {step === 3 &&
        (specLoading || !spec || !chosen ? (
          <Loading label="Loading method…" />
        ) : (
          <ParametersStep
            spec={spec}
            chosen={chosen}
            defaults={usingDefaults ? (initialParams ?? undefined) : undefined}
            onRun={handleRun}
            onBack={() => setStep(2)}
          />
        ))}

      {uploadSession.uploading && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              Uploading
              {Number.isFinite(uploadSession.progress ?? NaN) ? ` (${uploadSession.progress}%)` : ""}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => uploadSession.cancel()}>
              Cancel upload
            </Button>
          </div>
          <div className="h-2 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full rounded bg-primary transition-[width]"
              style={{ width: `${uploadSession.progress ?? 0}%` }}
            />
          </div>
        </div>
      )}
    </Card>
  );
}
