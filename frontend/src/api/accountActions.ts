import type { Client } from "./client";

export type FeedbackKind = "false_positive" | "true_positive" | "not_actionable";

export const postFeedback = (api: Client, accountId: string, kind: FeedbackKind, note?: string) =>
  api.post<{ id: string }>(`/accounts/${accountId}/feedback`, { kind, note });

export const suppressAccount = (api: Client, accountId: string, reason: string, days: number, now = new Date()) =>
  api.post<{ id: string; expires_at: string }>(`/accounts/${accountId}/suppress`, {
    reason,
    expires_at: new Date(now.getTime() + days * 86_400_000).toISOString(),
  });

export const liftSuppression = (api: Client, accountId: string) =>
  api.del<{ lifted: number }>(`/accounts/${accountId}/suppress`);
