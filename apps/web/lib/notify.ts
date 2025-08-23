import { toast } from "sonner";

// keep it loose-typed to avoid version/type churn
type ToastOpts = Record<string, any> | undefined;

export const notify = {
  success: (message: string, description?: string, opts?: ToastOpts) =>
    toast.success(message, { description, ...opts }),
  error: (message: string, description?: string, opts?: ToastOpts) =>
    toast.error(message, { description, ...opts }),
  info: (message: string, description?: string, opts?: ToastOpts) =>
    toast(message, { description, ...opts }),
};
