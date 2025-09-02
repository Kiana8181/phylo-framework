export type ApiEnvelope<T> = {
  status: "success" | "error";
  message?: string | null;
  data: T;
};

export const isEnvelope = (x: any): x is ApiEnvelope<unknown> =>
  !!x && typeof x === "object" && "status" in x && "data" in x;
