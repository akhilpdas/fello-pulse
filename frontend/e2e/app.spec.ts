import { expect, test, type Page } from "@playwright/test";

/**
 * The real UI, in a real browser, against the real API and a scratch copy of the demo database.
 * These are the interactions no unit test reaches: signing in and out, role-based pages, the queue, an account,
 * the account actions, the operator pages, and approving a draft end to end.
 */
test.describe.configure({ mode: "serial" });

const PASSWORD = process.env.PULSE_E2E_PASSWORD ?? "";
const OPERATOR = "csm00@northwind.example.com";
const CSM = "csm01@northwind.example.com";

async function signIn(page: Page, email: string, password = PASSWORD) {
  await page.goto("/");
  await page.getByLabel("Workspace").fill("northwind");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function belowCut(page: Page): Promise<number> {
  const text = await page.getByText(/more accounts? below the weekly capacity cut/).innerText();
  return Number(text.match(/^(\d+)/)![1]);
}

test("the password is available to the tests", () => {
  expect(PASSWORD.length, "run via `npm run e2e` so the demo password is passed in").toBeGreaterThan(11);
});

test("anyone who is not signed in sees only a sign-in form — no data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to Pulse" })).toBeVisible();
  await expect(page.getByText("This week's queue")).toHaveCount(0);
  await page.goto("/drafts");
  await expect(page.getByRole("heading", { name: "Sign in to Pulse" })).toBeVisible();
});

test("a wrong password is refused with one generic message", async ({ page }) => {
  await signIn(page, OPERATOR, "definitely not the password");
  await expect(page.getByRole("alert")).toHaveText("invalid credentials");
  await expect(page.getByText("This week's queue")).toHaveCount(0);
});

let operatorBelowCut = 0;

test("an operator signs in and sees the whole tenant's queue, and the Admin page", async ({ page }) => {
  const started = Date.now();
  await signIn(page, OPERATOR);
  await expect(page.getByText(/Dana Okafor · operator · northwind/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "This week's queue" })).toBeVisible();
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  expect(Date.now() - started, "SC-005: sign-in to a working queue").toBeLessThan(30_000);
  expect(await rows.count()).toBeGreaterThan(0);
  expect(await rows.count()).toBeLessThanOrEqual(12);
  await expect(page.getByRole("link", { name: "Admin" })).toBeVisible();
  operatorBelowCut = await belowCut(page);
  expect(operatorBelowCut).toBeGreaterThan(1000); // the whole tenant is behind the cut
});

test("the accounts below the weekly cut can be reached, paged through and filtered", async ({ page }) => {
  await signIn(page, OPERATOR);
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await page.getByRole("link", { name: /Browse all/ }).click();
  await expect(page.getByRole("heading", { name: "All accounts" })).toBeVisible();

  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBe(50);
  const summary = page.getByText(/^Showing 1–50 of [\d,]+/);
  await expect(summary).toBeVisible();
  const total = Number((await summary.innerText()).match(/of ([\d,]+)/)![1].replace(/,/g, ""));
  expect(total).toBeGreaterThan(operatorBelowCut); // everything behind the cut is in here, plus the queue itself

  // the first rows are this week's queue; paging goes past it, with ranks that carry on rather than restart
  await expect(rows.first().locator("td").first()).toHaveText("1");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText(/^Showing 51–100 of /)).toBeVisible();
  await expect(rows.first().locator("td").first()).toHaveText("51");
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.getByText(/^Showing 1–50 of /)).toBeVisible();

  // searching narrows the list and every row matches; a rank keeps its position in the full ranking
  const name = (await rows.nth(7).locator("td").nth(1).innerText()).split(" ")[0];
  await page.getByLabel("Search accounts").fill(name);
  const shownNames = async () => (await rows.locator("td:nth-child(2)").allInnerTexts()).map((n) => n.toLowerCase());
  await expect.poll(async () => { // the search is debounced, so wait for the narrowed list rather than reading the old one
    const names = await shownNames();
    return names.length > 0 && names.every((n) => n.includes(name.toLowerCase()));
  }).toBe(true);

  // filtering by tier leaves only that tier
  await page.getByLabel("Search accounts").fill("");
  await page.getByLabel("Tier").selectOption("red");
  await expect.poll(async () => {
    const tiers = (await rows.locator("td:nth-child(3)").allInnerTexts()).map((t) => t.toLowerCase());
    return tiers.length > 0 && tiers.every((t) => t.includes("red"));
  }).toBe(true);

  // a row opens the account
  await rows.first().getByRole("link").click();
  await expect(page.getByRole("heading", { name: "What is driving it" })).toBeVisible();
});

test("earlier weeks can be opened, and the latest queue shows what changed since the one before", async ({ page }) => {
  await signIn(page, OPERATOR);
  await expect(page.locator("table tbody tr").first()).toBeVisible();

  // the latest queue has history to compare against: not every row is "new"
  const deltas = await page.locator("table tbody tr td:last-child").allInnerTexts();
  expect(deltas.some((d) => d.trim() !== "new")).toBe(true);

  const week = page.getByLabel("Week");
  const options = await week.locator("option").allInnerTexts();
  expect(options.length).toBeGreaterThan(1);
  expect(options[0]).toContain("latest");
  const latestDate = await page.getByText(/^As of /).innerText();

  await week.selectOption({ index: 1 });
  await expect(page.getByText(/^As of /)).not.toHaveText(latestDate);
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  const chosen = await week.locator("option:checked").innerText();

  // the same week is selected when browsing everything, so the two views agree
  await page.getByRole("link", { name: /Browse all/ }).click();
  await expect(page.getByRole("heading", { name: "All accounts" })).toBeVisible();
  await expect(page.getByLabel("Week").locator("option:checked")).toHaveText(chosen);
});

test("\"What moved\" compares an account against an earlier week chosen from the weeks that exist", async ({ page }) => {
  // Found by reading the code while writing the walkthrough: the comparison needs a stored timestamp exactly, and the old
  // minute-precision date picker could not produce one, so every comparison from the UI was a 404.
  await signIn(page, OPERATOR);
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await page.locator("table tbody tr").first().getByRole("link").click();
  await expect(page.getByRole("heading", { name: "What moved" })).toBeVisible();

  const picker = page.getByLabel("Compare against the score as of");
  await expect(picker.locator("option")).not.toHaveCount(0);
  await picker.selectOption({ index: 1 }); // index 0 is the placeholder
  await page.getByRole("button", { name: "Compare" }).click();

  await expect(page.getByText(/%\s*→\s*[\d.]+%/)).toBeVisible(); // "12.3% → 14.0% (▲ 1.7 pts)"
  await expect(page.getByText("Contribution change")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("approving a draft says right away what happened, including when nothing was sent", async ({ page }) => {
  // Found while taking the walkthrough screenshots: with outbound off, Approve made the draft vanish from the
  // "drafted" list and the reason was only visible after switching the filter -- so it looked as if it had been sent.
  await signIn(page, OPERATOR);
  await page.getByRole("link", { name: "Drafts" }).click();
  const cards = page.locator("article.draft");
  await expect(cards.first()).toBeVisible();
  const before = await cards.count();
  await cards.first().getByRole("button", { name: "Approve & send" }).click();

  const notice = page.locator(".draft-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("Not sent: outbound email is switched off");
  await expect(cards).toHaveCount(before - 1); // it left the "drafted" list, and the notice is what tells you why
  await page.getByLabel("Show").selectOption("outbound_disabled");
  await expect(page.locator("article.draft").first()).toBeVisible(); // and it is findable under its new state
});

test("an account shows its drivers and evidence, and the CSM's judgement is recorded and the account can be suppressed", async ({ page }) => {
  await signIn(page, OPERATOR);
  const first = page.locator("table tbody tr").first().getByRole("link");
  const name = await first.innerText();
  const href = await first.getAttribute("href"); // account names repeat within a tenant, so identify it by its link
  await first.click();
  await expect(page.getByRole("heading", { name: new RegExp(name) })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What is driving it" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();

  await page.getByRole("button", { name: "Confirm risk is real" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Recorded as a true positive." })).toBeVisible();

  await page.getByPlaceholder("why suppress? (required)").fill("e2e: deliberately letting this one go");
  await page.getByRole("button", { name: "Suppress from queue" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Suppressed from the queue for 14 days; still scored\./ })).toBeVisible();

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByRole("heading", { name: "This week's queue" })).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await expect(page.locator(`table tbody a[href="${href}"]`)).toHaveCount(0); // that account is gone from the queue
});

test("an operator sets up outbound email, manages opt-outs and users, and the audit trail records it", async ({ page }) => {
  await signIn(page, OPERATOR);
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page.getByRole("heading", { name: "Outbound email" })).toBeVisible();
  await expect(page.getByText("ON — nothing reaches customers")).toBeVisible(); // demo mode is the default

  // you cannot switch it on before the sender is verified: the button is disabled until it is
  await expect(page.getByRole("button", { name: "Switch outbound on" })).toBeDisabled();
  await page.getByLabel("Sender address").fill("csm@northwind.example.com");
  await page.getByRole("button", { name: "Set sender" }).click();
  await page.getByRole("button", { name: "Verify sender" }).click();
  await page.getByRole("button", { name: "Switch outbound on" }).click();
  await expect(page.getByRole("button", { name: "Switch outbound off" })).toBeVisible();

  await page.getByLabel("Opt-out email").fill("gone@acme.example.com");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const optOut = page.getByRole("listitem").filter({ hasText: "gone@acme.example.com" });
  await expect(optOut).toBeVisible();
  await optOut.getByRole("button", { name: "Remove" }).click();
  await expect(optOut).toHaveCount(0);

  await page.getByLabel("New user email").fill("e2e.user@northwind.example.com");
  await page.getByLabel("New user name").fill("E2E User");
  await page.getByLabel("New user password").fill("a long e2e passphrase");
  await page.getByRole("button", { name: "Create user" }).click();
  const users = page.locator("section", { has: page.getByRole("heading", { name: "Users" }) });
  await expect(users.getByRole("cell", { name: "e2e.user@northwind.example.com" })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Audit trail" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "outbound_changed" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "user_created" }).first()).toBeVisible();
});

test("approving a draft never reaches a customer in demo mode, and says so", async ({ page }) => {
  await signIn(page, OPERATOR);
  await page.getByRole("link", { name: "Drafts" }).click();
  await expect(page.getByRole("heading", { name: "Draft review" })).toBeVisible();
  const cards = page.locator("article.draft");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first().getByText("Waiting for your review.")).toBeVisible();

  // Some accounts have no known contact (about 1 in 9 drafts) and are correctly blocked, and they cluster together in
  // the list -- so keep approving until one is delivered (here: captured, because demo mode is on), rather than
  // assuming the first few have an address.
  const sentCount = () => page.evaluate(async () => (await (await fetch("/api/actions?state=sent", { credentials: "include" })).json()).rows.length);
  let approved = 0;
  while ((await sentCount()) === 0 && approved < 60) {
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/approve") && r.request().method() === "POST"),
      page.locator("article.draft").first().getByRole("button", { name: "Approve & send" }).click(),
    ]);
    expect(response.status()).toBe(200);
    approved += 1;
    await page.waitForLoadState("networkidle");
  }
  expect(await sentCount(), `none of ${approved} approved drafts was delivered`).toBeGreaterThan(0);
  await page.getByLabel("Show").selectOption("sent");
  await expect(page.getByText("Demo mode: captured but not delivered — no customer was emailed.").first()).toBeVisible();
  await expect(page.getByText("Sent to the customer.")).toHaveCount(0); // nothing real was sent
});

test("a CSM sees only their own accounts, no Admin page, and the server refuses the admin API", async ({ page }) => {
  await signIn(page, CSM);
  await expect(page.getByText(/Priya Rossi · csm · northwind/)).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  const csmBelowCut = await belowCut(page);
  expect(csmBelowCut).toBeLessThan(operatorBelowCut / 5); // a CSM's own book, not the tenant

  await page.goto("/admin");
  await expect(page.getByText("This page is for operators.")).toBeVisible();
  const status = await page.evaluate(async () => (await fetch("/api/admin/outbound", { credentials: "include" })).status);
  expect(status).toBe(403);
});

test("signing out ends the session", async ({ page }) => {
  await signIn(page, CSM);
  await expect(page.getByRole("heading", { name: "This week's queue" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to Pulse" })).toBeVisible();
  const status = await page.evaluate(async () => (await fetch("/api/queue", { credentials: "include" })).status);
  expect(status).toBe(401);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in to Pulse" })).toBeVisible();
});
