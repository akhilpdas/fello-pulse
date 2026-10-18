import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { friendlyError, isWakingUp } from "./coldStart";

describe("a free host sleeps when idle and takes about a minute to wake", () => {
  it.each([502, 503, 504])("treats a %i from the platform as 'waking up'", (status) => {
    expect(isWakingUp(new ApiError(status, "Bad Gateway"))).toBe(true);
  });
  it("treats a request that never reached the server as 'waking up'", () => {
    expect(isWakingUp(new TypeError("Failed to fetch"))).toBe(true);
  });
  it("does not blame the host for a wrong password or a real server error", () => {
    expect(isWakingUp(new ApiError(401, "invalid credentials"))).toBe(false);
    expect(isWakingUp(new ApiError(500, "Internal Server Error"))).toBe(false);
    expect(isWakingUp(new ApiError(429, "too many attempts"))).toBe(false);
  });
});

describe("friendlyError", () => {
  it("explains the wait and says to try again", () => {
    const m = friendlyError(new ApiError(503, "Service Unavailable"));
    expect(m).toMatch(/waking/i);
    expect(m).toMatch(/minute/i);
  });
  it("leaves every other message exactly as the server gave it", () => {
    expect(friendlyError(new ApiError(401, "invalid credentials"))).toBe("invalid credentials");
    expect(friendlyError(new Error("boom"))).toBe("boom");
  });
});
