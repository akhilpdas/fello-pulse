import { describe, expect, it } from "vitest";
import { driverLabel, formatDelta, formatFeatureValue, formatMoney, formatPercent, renewalLabel, tierRank } from "./format";

describe("formatMoney", () => {
  it("renders cents as whole dollars with grouping", () => {
    expect(formatMoney(12_345_600)).toBe("$123,456");
  });
  it("renders missing value as an em dash, never $0", () => {
    expect(formatMoney(null)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("renders a probability as a percentage", () => expect(formatPercent(0.347)).toBe("34.7%"));
});

describe("formatDelta", () => {
  it("signs movement in percentage points", () => {
    expect(formatDelta(0.052)).toBe("▲ 5.2 pts");
    expect(formatDelta(-0.031)).toBe("▼ 3.1 pts");
  });
  it("says 'new' when there is no previous score", () => expect(formatDelta(null)).toBe("new"));
  it("treats sub-0.05pt movement as flat", () => expect(formatDelta(0.0002)).toBe("— flat"));
});

describe("renewalLabel", () => {
  it("is explicit about overdue and unknown renewals", () => {
    expect(renewalLabel(12)).toBe("12 days");
    expect(renewalLabel(-3)).toBe("3 days overdue");
    expect(renewalLabel(null)).toBe("no renewal date");
  });
});

describe("driverLabel", () => {
  it("humanises driver keys and labels data quality as such, not customer behaviour", () => {
    expect(driverLabel("support")).toBe("Support");
    expect(driverLabel("data_quality")).toBe("Data quality (not customer behaviour)");
    expect(driverLabel(null)).toBe("—");
  });
});

describe("tierRank", () => {
  it("orders red before amber before green, with abstain last", () => {
    const tiers = ["green", "abstain", "red", "amber"].sort((a, b) => tierRank(a) - tierRank(b));
    expect(tiers).toEqual(["red", "amber", "green", "abstain"]);
  });
});

describe("formatFeatureValue", () => {
  it("shows a missing value as a dash, never as zero", () => {
    expect(formatFeatureValue(null)).toBe("—");
    expect(formatFeatureValue(undefined)).toBe("—");
  });
  it("keeps whole numbers whole", () => {
    expect(formatFeatureValue(84223342)).toBe("84223342");
    expect(formatFeatureValue(2)).toBe("2");
    expect(formatFeatureValue(0)).toBe("0");
  });
  it("trims long fractions to three significant digits", () => {
    expect(formatFeatureValue(0.05083260297984225)).toBe("0.0508");
    expect(formatFeatureValue(3.8683333333333333)).toBe("3.87");
    expect(formatFeatureValue(0.5918367346938777)).toBe("0.592");
  });
});
