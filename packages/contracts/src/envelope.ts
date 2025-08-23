export type ApiEnvelope<T> = {
  status: "success" | "error";
  message?: string | null;
  data: T;
};

export function isEnvelope(x: any): x is ApiEnvelope<unknown> {
  return !!x && typeof x === "object" && "status" in x && "data" in x;
}
