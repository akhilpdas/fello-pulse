import { ApiError, type Client } from "./client";

export interface Who {
  user: { id: string; name: string; email: string; role: "csm" | "operator" };
  tenant: { id: string; slug: string };
}

export const login = (api: Client, workspace: string, email: string, password: string) =>
  api.post<Who>("/auth/login", { workspace, email, password });

/** Who the session cookie belongs to; `null` when not signed in. */
export async function fetchMe(api: Client): Promise<Who | null> {
  try {
    return await api.get<Who>("/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export const logout = (api: Client) => api.post<{ ok: boolean }>("/auth/logout", {});
