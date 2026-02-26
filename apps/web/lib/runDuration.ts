function parseIsoMillis(value?: string | null): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function formatDurationSeconds(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds}s`;

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) return `${hours}h ${remainingMinutes}m`;

  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return `${days}d ${remainingHours}h`;
}

export function formatRunDuration(
  startedAt?: string | null,
  finishedAt?: string | null
): string | null {
  const startedMs = parseIsoMillis(startedAt);
  if (startedMs == null) return null;

  const finishedMs = parseIsoMillis(finishedAt);
  if (finishedMs == null) return null;
  const endMs = finishedMs;
  if (endMs < startedMs) return null;

  const totalSeconds = Math.max(0, Math.round((endMs - startedMs) / 1000));
  return formatDurationSeconds(totalSeconds);
}
