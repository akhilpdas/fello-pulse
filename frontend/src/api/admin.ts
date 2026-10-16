import type { Client } from "./client";

export interface Outbound {
  outbound_enabled: boolean; sender_address: string | null; sender_verified: boolean;
  demo_mode: boolean; test_inbox: string | null; smtp_configured: boolean;
}
export type OutboundPatch = Partial<Omit<Outbound, "smtp_configured">>;
export interface OptOut { id: string; email: string; reason: string | null; created_at: string }
export interface AdminUser { id: string; email: string; name: string; role: "csm" | "operator"; disabled: boolean }
export interface AuditEvent {
  at: string; actor_kind: string; actor_user_id: string | null; event: string; subject: string | null; detail: Record<string, unknown>;
}

export const getOutbound = (api: Client) => api.get<Outbound>("/admin/outbound");
export const patchOutbound = (api: Client, patch: OutboundPatch) => api.patch<Outbound>("/admin/outbound", patch);

export const listOptOuts = (api: Client) => api.get<OptOut[]>("/admin/opt-outs");
export const addOptOut = (api: Client, email: string, reason?: string) =>
  api.post<{ id: string; email: string }>("/admin/opt-outs", { email, reason });
export const removeOptOut = (api: Client, id: string) => api.del<{ removed: string }>(`/admin/opt-outs/${id}`);

export const listUsers = (api: Client) => api.get<AdminUser[]>("/admin/users");
export const createUser = (api: Client, u: { email: string; name: string; role: "csm" | "operator"; password: string }) =>
  api.post<AdminUser>("/admin/users", u);
export const patchUser = (api: Client, id: string, patch: { role?: "csm" | "operator"; disabled?: boolean; password?: string; name?: string }) =>
  api.patch<AdminUser>(`/admin/users/${id}`, patch);

export const getAudit = (api: Client) => api.get<AuditEvent[]>("/admin/audit");
