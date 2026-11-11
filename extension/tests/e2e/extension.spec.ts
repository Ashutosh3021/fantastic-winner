import { expect, test } from "@playwright/test";

import { TWO_SUM_FIXTURE } from "./fixture";
import { fakeState, launchExtension, setPlanTier } from "./harness";

test("signed-in popup and the full learning loop", async () => {
  test.setTimeout(120_000);
  const { context, extensionId } = await launchExtension();

  try {
    await context.route("https://leetcode.com/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === "/problems/two-sum/") {
        return route.fulfill({
          status: 200,
          contentType: "text/html; charset=utf-8",
          body: TWO_SUM_FIXTURE,
        });
      }
      return route.fulfill({ status: 404, body: "not found" });
    });

    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await expect(popup.getByRole("heading", { name: "Concept mastery" })).toBeVisible({
      timeout: 20_000,
    });
    await popup.getByRole("tab", { name: "Account" }).click();
    await expect(popup.getByText("Signed in", { exact: true })).toBeVisible();
    await expect(popup.getByText("e2e@example.com", { exact: true })).toBeVisible();

    // Own-key settings: save masks the key, remove clears it.
    await popup.getByPlaceholder("sk-…").fill("sk-e2e-own-key-1234");
    await popup.getByRole("button", { name: "Save", exact: true }).click();
    await expect(popup.getByText("••••1234")).toBeVisible();

    // A tier-1 account with a key is uncapped; removing the key restores metering.
    await setPlanTier(1);
    await popup.reload();
    await popup.getByRole("tab", { name: "Account" }).click();
    await expect(popup.getByText("Unlimited with your key")).toBeVisible();
    await popup.getByRole("button", { name: "Remove" }).click();
    await expect(popup.getByText("••••1234")).toBeHidden();
    await expect(popup.getByText("Unlimited with your key")).toBeHidden();
    await setPlanTier(0);

    await popup.close();

    const page = await context.newPage();
    await page.goto("https://leetcode.com/problems/two-sum/");
    // The overlay is injected on demand, so the launcher is the entry point.
    await page.locator("#codementor-launcher").click();
    const overlay = page.getByRole("complementary", { name: "CodeMentor" });

    await expect(overlay.getByRole("heading", { name: "Two Sum" })).toBeVisible({
      timeout: 30_000,
    });
    // Proves the shadow-root stylesheet was fetched from the extension origin.
    await expect(overlay).toHaveCSS("width", "352px");
    await overlay.getByRole("button", { name: /Brute Force/ }).click();
    await expect(
      overlay.getByRole("heading", { name: "Brute Force Walkthrough" }),
    ).toBeVisible();

    await overlay.getByRole("button", { name: /Hash Map/ }).click();
    const confirm = overlay.getByRole("alertdialog");
    await expect(confirm).toBeVisible();
    await expect(
      confirm.getByRole("heading", { name: "Switch to Hash Map?" }),
    ).toBeVisible();
    await expect(confirm).toContainText("3 question credits");
    await expect(confirm).toContainText("12 remaining");
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();
    await expect(
      overlay.getByRole("heading", { name: "Brute Force Walkthrough" }),
    ).toBeVisible();

    await overlay.getByRole("button", { name: /Hash Map/ }).click();
    await overlay
      .getByRole("alertdialog")
      .getByRole("button", { name: "Switch and reset progress" })
      .click();
    await expect(
      overlay.getByRole("heading", { name: "Hash Map Walkthrough" }),
    ).toBeVisible();

    const switched = await fakeState();
    expect(switched.switchCount).toBe(1);
    expect(switched.planGenerated).toBe(0);
    expect(switched.question).toBeNull();

    const prompt = "What should the hash map store while you scan the array?";
    await overlay.getByRole("button", { name: "Start micro-questions" }).click();
    await expect(overlay.getByText(prompt)).toBeVisible();

    await page.reload();
    await page.locator("#codementor-launcher").click();
    await expect(overlay.getByText(prompt)).toBeVisible({ timeout: 30_000 });

    await overlay.getByRole("button", { name: /Need a hint/ }).click();
    await expect(overlay.getByText("Hint 1 of 3")).toBeVisible();
    await expect(
      overlay.getByText("Remember which values you have already walked past."),
    ).toBeVisible();

    const answer = overlay.getByRole("textbox", { name: "Your answer" });
    const check = overlay.getByRole("button", { name: "Check understanding" });
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      await answer.fill(`wrong answer ${attempt}`);
      await check.click();
      await expect.poll(async () => (await fakeState()).attempts).toBe(attempt);
    }

    await expect(overlay.getByText("Not yet.")).toBeVisible();
    await overlay.getByRole("button", { name: "Show me this step" }).click();
    await expect(overlay.getByText("This step, in words")).toBeVisible();
    await expect(
      overlay.getByText(
        "Before you store the current value, check whether its complement is already in the map.",
      ),
    ).toBeVisible();

    await answer.fill("store the complement index for every value");
    await check.click();
    await expect(
      overlay.getByRole("heading", { name: "You've completed all micro-questions." }),
    ).toBeVisible();

    await overlay.getByRole("button", { name: "Open Solution Analysis" }).click();
    await expect(
      overlay.getByRole("heading", { name: "Solution Analysis" }),
    ).toBeVisible();
    await expect(
      overlay.getByText("One pass over the array, with constant-time hash lookups."),
    ).toBeVisible();

    const finished = await fakeState();
    expect(finished.completed).toBe(true);
    expect(finished.analysisCalls).toBe(1);
  } finally {
    await context.close();
  }
});
