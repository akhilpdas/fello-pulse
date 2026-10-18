// Captures the screenshots used in docs/Pulse_Test_Walkthrough.docx from the real UI, in real Chrome.
// It is run against a SCRATCH copy of the demo data (see docs/walkthrough/README.md), never the demo database itself.
//   UI=http://127.0.0.1:8273 MAIL=http://127.0.0.1:8025 PW=<demo password> node docs/walkthrough/capture.mjs
import { chromium } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { mkdirSync } from "node:fs";

const UI = process.env.UI ?? "http://127.0.0.1:8273";
const MAIL = process.env.MAIL ?? "http://127.0.0.1:8025";
const PW = process.env.PW;
const OUT = new URL("./img/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
if (!PW) throw new Error("set PW to the demo password");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1.5 });
const page = await ctx.newPage();

/** Outline elements in red so the reader can see exactly what to click/look at, screenshot, then remove the outline. */
async function shot(name, { marks = [], full = true, scrollTo = null, clip = null } = {}) {
  if (scrollTo) await scrollTo.evaluate((el) => el.scrollIntoView({ block: "start" }));
  for (const m of marks) await m.evaluate((el) => { el.dataset.prevOutline = el.style.outline; el.style.outline = "3px solid #e11d48"; el.style.outlineOffset = "3px"; });
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${OUT}${name}.png`, fullPage: full && !clip, ...(clip ? { clip } : {}) });
  for (const m of marks) await m.evaluate((el) => { el.style.outline = el.dataset.prevOutline ?? ""; });
  console.log("captured", name);
}
const signIn = async (email) => {
  await page.goto(UI + "/");
  await page.getByLabel("Workspace").fill("northwind");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.locator("table tbody tr").first().waitFor();
};
const rows = () => page.locator("table tbody tr");

// ---- 1. Sign in ----
await page.goto(UI + "/");
await page.getByLabel("Workspace").fill("northwind");
await page.getByLabel("Email").fill("csm00@northwind.example.com");
await page.getByLabel("Password").fill("••••••••••••");
await shot("01-sign-in", { marks: [page.getByLabel("Workspace"), page.getByLabel("Email"), page.getByLabel("Password"), page.getByRole("button", { name: "Sign in" })], full: false, clip: { x: 0, y: 0, width: 1280, height: 493 } });

// ---- 2. Queue ----
await signIn("csm00@northwind.example.com");
await shot("02-queue", { marks: [page.getByLabel("Week"), page.getByRole("link", { name: /Browse all/ })] });
await shot("03-nav-operator", { marks: [page.locator("header.top")], full: false, clip: { x: 0, y: 0, width: 1280, height: 87 } });

// ---- 3. Earlier week ----
await page.getByLabel("Week").selectOption({ index: 2 });
await rows().first().waitFor();
await page.waitForTimeout(500);
await shot("04-queue-earlier-week", { marks: [page.getByLabel("Week"), page.getByText(/^As of /)] });
await page.getByLabel("Week").selectOption({ index: 0 });
await page.waitForTimeout(500);

// ---- 4. Browse all ----
await page.getByRole("link", { name: /Browse all/ }).click();
await page.getByRole("heading", { name: "All accounts" }).waitFor();
await rows().first().waitFor();
await shot("05-browse-all", { marks: [page.getByLabel("Search accounts"), page.getByLabel("Tier"), page.getByLabel("Driver"), page.getByRole("button", { name: "Next" })], full: false });
await page.getByRole("button", { name: "Next" }).click();
await page.getByText(/^Showing 51–100/).waitFor();
await shot("06-browse-page-2", { marks: [page.getByText(/^Showing 51–100/), rows().first().locator("td").first()], scrollTo: page.getByRole("button", { name: "Previous" }) , full: false });
await page.getByRole("button", { name: "Previous" }).click();
await page.getByText(/^Showing 1–50/).waitFor();
await page.getByLabel("Tier").selectOption("red");
await page.getByLabel("Driver").selectOption("usage_decline");
await page.waitForTimeout(900);
await shot("07-browse-filtered", { marks: [page.getByLabel("Tier"), page.getByLabel("Driver")], full: false });
await page.getByLabel("Tier").selectOption("");
await page.getByLabel("Driver").selectOption("");

// ---- 5. Account page ----
await page.getByRole("link", { name: "← This week's queue" }).click();
await rows().first().waitFor();
await rows().first().getByRole("link").click();
await page.getByRole("heading", { name: "What is driving it" }).waitFor();
await shot("08-account-top", { marks: [page.getByRole("heading", { name: "What is driving it" })], full: false });
const evBtn = page.locator("button.link").first();
await evBtn.click();
await page.locator("details.event").first().waitFor();
await page.locator("details.event summary").first().click();
await shot("09-account-evidence", { marks: [evBtn, page.locator("details.event").first()], scrollTo: page.getByRole("heading", { name: "Evidence" }), full: false });
const picker = page.getByLabel("Compare against the score as of");
await picker.selectOption({ index: 2 });
await page.getByRole("button", { name: "Compare" }).click();
await page.getByText("Contribution change").waitFor();
await shot("10-account-what-moved", { marks: [picker, page.getByRole("button", { name: "Compare" })], scrollTo: page.getByRole("heading", { name: "What moved" }), full: false });
await shot("11-account-judgement", { marks: [page.getByRole("button", { name: "Confirm risk is real" }), page.getByRole("button", { name: "Mark false positive" }), page.getByRole("button", { name: "Suppress from queue" })], scrollTo: page.getByRole("heading", { name: "Your judgement" }), full: false });

// ---- 6. Low confidence ----
await page.getByRole("link", { name: "Low confidence" }).click();
await page.getByRole("heading", { name: "Low confidence" }).waitFor();
await page.waitForTimeout(600);
await shot("12-low-confidence", { full: false });

// ---- 7. Drafts: blocked while outbound is off ----
await page.getByRole("link", { name: "Drafts" }).click();
await page.getByRole("heading", { name: "Draft review" }).waitFor();
await page.locator("article.draft").first().waitFor();
await shot("13-drafts-review", { marks: [page.locator("article.draft").first().getByLabel("Subject"), page.locator("article.draft").first().getByRole("button", { name: "Approve & send" })], full: false });
await page.locator("article.draft").first().getByRole("button", { name: "Approve & send" }).click();
await page.locator(".draft-notice").waitFor();
await shot("14-drafts-blocked-outbound-off", { marks: [page.locator(".draft-notice")], full: false });
await page.getByLabel("Show").selectOption("outbound_disabled");

// ---- 8. Admin: outbound ----
await page.getByRole("link", { name: "Admin" }).click();
await page.getByRole("heading", { name: "Outbound email" }).waitFor();
await shot("15-admin-outbound-before", { marks: [page.getByRole("button", { name: "Switch outbound on" })], full: false });
await page.getByLabel("Sender address").fill("csm@northwind.example.com");
await page.getByRole("button", { name: "Set sender" }).click();
await page.getByRole("button", { name: "Verify sender" }).click();
await page.getByRole("button", { name: "Switch outbound on" }).click();
await page.getByLabel("Test inbox").fill("demo-inbox@northwind.example.com");
await page.getByRole("button", { name: "Set test inbox" }).click();
await page.getByText("demo-inbox@northwind.example.com").first().waitFor();
await shot("16-admin-outbound-on", { marks: [page.getByText("✓ verified"), page.getByRole("button", { name: "Switch outbound off" })], full: false });
await page.getByLabel("Opt-out email").fill("someone@acme.example.com");
await page.getByRole("button", { name: "Add", exact: true }).click();
await page.getByText("someone@acme.example.com").first().waitFor();
await shot("17-admin-opt-outs", { marks: [page.getByLabel("Opt-out email")], scrollTo: page.getByRole("heading", { name: "Opt-outs" }), full: false });
await shot("18-admin-users", { marks: [page.getByLabel("New user email")], scrollTo: page.getByRole("heading", { name: "Users" }), full: false });
await shot("19-admin-audit", { marks: [], scrollTo: page.getByRole("heading", { name: "Audit trail" }), full: false });

// ---- 9. Approve in demo mode -> Mailpit ----
await page.getByRole("link", { name: "Drafts" }).click();
await page.getByRole("heading", { name: "Draft review" }).waitFor();
await page.getByLabel("Show").selectOption("outbound_disabled");
await page.locator("article.draft").first().waitFor();
await page.locator("article.draft").first().getByRole("button", { name: "Approve & send" }).click();
await page.locator(".draft-notice", { hasText: "Demo mode: sent to the test inbox" }).waitFor();
await shot("20-drafts-sent-demo", { marks: [page.locator(".draft-notice")], full: false });
const mail = await ctx.newPage();
await mail.goto(MAIL);
await mail.waitForTimeout(1500);
await mail.setViewportSize({ width: 1280, height: 700 });
await mail.screenshot({ path: `${OUT}21-mailpit-inbox.png` });
await mail.locator("#message-list a, .message a, a.list-group-item").first().click().catch(() => {});
await mail.waitForTimeout(1200);
await mail.screenshot({ path: `${OUT}22-mailpit-message.png` });
console.log("captured mailpit");

// ---- 10. Run log ----
await page.bringToFront();
await page.getByRole("link", { name: "Run log" }).click();
await page.getByRole("heading", { name: "Run log" }).waitFor();
await page.locator("article.run").first().waitFor();
await page.locator("article.run").first().locator("summary").click();
await shot("23-run-log", { marks: [page.locator("article.run").first().locator("summary")], full: false });

// ---- 11. A CSM's view ----
await page.getByRole("button", { name: "Sign out" }).click();
await signIn("csm01@northwind.example.com");
await shot("24-csm-queue", { marks: [page.locator("header.top nav")], full: false });
await page.goto(UI + "/admin");
await page.getByText("This page is for operators.").waitFor();
await shot("25-csm-no-admin", { marks: [page.getByText("This page is for operators.")], full: false, clip: { x: 0, y: 0, width: 1280, height: 220 } });

await browser.close();
console.log("done");
