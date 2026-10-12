import { CalendarClock } from "lucide-react";
import { daysLeftLabel, retentionState, type RetentionFields } from "@/features/runs/retention";

/**
 * Says until when a finished run's results are kept and, afterwards, that they
 * are gone. Shown on the run page both before and after the date, so removal
 * never comes as a surprise and an expired run explains itself.
 *
 * `what` names what is kept: the results of a finished run, or the log of a
 * failed one.
 */
export default function ResultRetentionNotice({
  run,
  what = "results",
  now,
  className,
}: {
  run: RetentionFields | null | undefined;
  what?: "results" | "log";
  /** Milliseconds since epoch; defaults to the current time. */
  now?: number;
  className?: string;
}) {
  const state = retentionState(run, now);
  if (state.kind === "none") return null;

  if (state.kind === "expired") {
    return (
      <div
        data-testid="result-retention"
        data-state="expired"
        role="status"
        className={`flex items-start gap-2 rounded border p-3 text-sm bg-muted text-foreground ${className ?? ""}`}
      >
        <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          <span className="font-medium">
            {what === "log" ? "The log of this run" : "The results of this run"} expired
            {state.on ? ` on ${state.on}` : ""} and {what === "log" ? "was" : "were"} removed.
          </span>{" "}
          The run stays in your history with its settings.
          {what === "results" ? " To get the results again, run it again." : ""}
        </p>
      </div>
    );
  }

  const subject = what === "log" ? "The log of this run is" : "These results are";
  const tone = state.soon
    ? "bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
    : "text-muted-foreground";
  return (
    <div
      data-testid="result-retention"
      data-state={state.due ? "due" : state.soon ? "soon" : "kept"}
      className={`flex items-start gap-2 rounded border p-3 text-sm ${tone} ${className ?? ""}`}
    >
      <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      {state.due ? (
        <p>
          {subject} past the date until which {what === "log" ? "it is" : "they are"} kept ({state.until}) and will be
          removed shortly.
        </p>
      ) : (
        <p>
          {subject} kept until <span className="font-medium">{state.until}</span> ({daysLeftLabel(state.daysLeft)}).
          {what === "results" ? " Download what you need before then; after that date they are removed." : ""}
        </p>
      )}
    </div>
  );
}
