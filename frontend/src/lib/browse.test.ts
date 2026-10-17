import { describe, expect, it } from "vitest";
import { browseQuery, pageWindow, snapshotLabel } from "./browse";

describe("browseQuery", () => {
  it("sends only what the user set, and turns a page number into an offset", () => {
    expect(browseQuery({ q: "", tier: "", driver: "", asOf: "", page: 0, pageSize: 50 }))
      .toEqual({ offset: 0, limit: 50 });
    expect(browseQuery({ q: " acme ", tier: "red", driver: "support", asOf: "2026-10-01T09:00:00+00:00", page: 3, pageSize: 25 }))
      .toEqual({ q: "acme", tier: "red", driver: "support", as_of: "2026-10-01T09:00:00+00:00", offset: 75, limit: 25 });
  });
});

describe("pageWindow", () => {
  it("describes the rows on screen and whether there is a previous/next page", () => {
    expect(pageWindow(120, 0, 50)).toEqual({ from: 1, to: 50, hasPrev: false, hasNext: true });
    expect(pageWindow(120, 100, 50)).toEqual({ from: 101, to: 120, hasPrev: true, hasNext: false });
  });
  it("says so when nothing matches", () => {
    expect(pageWindow(0, 0, 50)).toEqual({ from: 0, to: 0, hasPrev: false, hasNext: false });
  });
  it("does not offer a next page when the total is an exact multiple", () => {
    expect(pageWindow(100, 50, 50)).toEqual({ from: 51, to: 100, hasPrev: true, hasNext: false });
  });
});

describe("snapshotLabel", () => {
  it("shows the date and how many accounts were scored, marking the newest as current", () => {
    expect(snapshotLabel({ as_of: "2026-10-01T09:00:00+00:00", scored: 2512 }, true)).toBe("1 Oct 2026 · 2,512 scored · latest");
    expect(snapshotLabel({ as_of: "2026-09-24T09:00:00+00:00", scored: 2500 }, false)).toBe("24 Sep 2026 · 2,500 scored");
  });
});
