import { ApiError } from "../api/client";

/** A free host puts an idle service to sleep and takes about a minute to wake it; until then the platform answers
 *  502/503/504 or the request never arrives. That is the host, not a wrong password, and must not read like one. */
export function isWakingUp(e: unknown): boolean {
  if (e instanceof ApiError) return e.status === 502 || e.status === 503 || e.status === 504;
  return e instanceof TypeError;   // fetch could not reach the server at all
}

export function friendlyError(e: unknown): string {
  if (isWakingUp(e)) {
    return "The demo server is waking up (free hosting sleeps when idle). This takes about a minute — please try again shortly.";
  }
  return (e as Error).message;
}
