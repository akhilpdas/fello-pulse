import { describe, expect, it } from "vitest";
import { navFor } from "./nav";

describe("navigation by role (002 / FR-011)", () => {
  it("never shows a CSM an operator-only page", () => {
    const labels = navFor("csm").map((n) => n.label);
    expect(labels).toEqual(["Queue", "Low confidence", "Drafts", "Run log"]);
    expect(navFor("csm").some((n) => n.operatorOnly)).toBe(false);
  });
  it("gives an operator the same pages plus the admin page", () => {
    const labels = navFor("operator").map((n) => n.label);
    expect(labels).toEqual(["Queue", "Low confidence", "Drafts", "Run log", "Admin"]);
    expect(navFor("operator").find((n) => n.label === "Admin")?.to).toBe("/admin");
  });
});
