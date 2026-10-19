# E2E recipes

## Start the app under test

Use the project's own command (from `package.json` scripts, `Makefile`, or the brief) and start it
detached so the Bash call returns in both runtimes (`run_in_background` is disabled under
`bin/stack-sdk run`, which sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`):
`nohup <command> > .stack/out/tester/server.log 2>&1 & echo $! > .stack/out/tester/server.pid`;
stop it when done with `kill "$(cat .stack/out/tester/server.pid)"`. Then wait until the port answers:

```bash
# polls up to ~30 s without a shell sleep; exits non-zero if the server never answers
curl -sf --retry 30 --retry-delay 1 --retry-connrefused -o /dev/null http://localhost:3000/ && echo up
```

Navigate only to the local host the brief names. Test accounts come from the project's seed or
fixture files or the brief; record which file in Evidence, never the values.

## Recipe: signup happy path (MCP run)

1. `browser_navigate {url: "http://localhost:3000/signup"}`
2. `browser_snapshot` -> textbox "Email" e8, textbox "Password" e9, button "Create account" e11
3. `browser_fill_form {fields: [{name: "Email", type: "textbox", target: "e8", value: "<fixture email>"}, {name: "Password", type: "textbox", target: "e9", value: "<fixture password>"}]}`
4. `browser_click {element: "Create account button", target: "e11"}`
5. `browser_wait_for {text: "Welcome"}`; on timeout: `browser_console_messages {level: "error"}`,
   `browser_network_requests {static: false}`, screenshot.
6. Assert: snapshot contains heading "Welcome"; URL is `/dashboard`.

## Recipe: responsive layout check

`browser_resize {width: 375, height: 812}` -> snapshot + screenshot; repeat at 768x1024 and
1280x800. Assert the navigation collapses into a button named "Menu" (or whatever the snapshot shows)
and no horizontal scroll: `browser_evaluate {function: "() => document.documentElement.scrollWidth <= window.innerWidth"}`.

## Recipe: error-state check

Trigger validation by submitting empty required fields; assert the error texts appear and that focus
moved to the first invalid field:
`browser_evaluate {function: "() => document.activeElement?.getAttribute('name')"}`.

## Turning a run into a regression test

Write `tests/e2e/<feature>.spec.ts` (or the project's existing E2E directory and language) using the
roles and names from the snapshot. Locators by role mirror what the MCP saw, which keeps tests stable.

```ts
import { test, expect } from '@playwright/test';

test('signup shows welcome for a new account', async ({ page }) => {
  await page.goto('http://localhost:3000/signup');
  await page.getByRole('textbox', { name: 'Email' }).fill(process.env.E2E_EMAIL ?? 'new-user@example.test');
  await page.getByRole('textbox', { name: 'Password' }).fill(process.env.E2E_PASSWORD ?? 'fixture-only');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome' })).toBeVisible();
  await expect(page).toHaveURL(/\/dashboard$/);
});
```

Run and capture evidence:

```bash
npx playwright test tests/e2e/signup.spec.ts --reporter=line
npx playwright test tests/e2e/signup.spec.ts --repeat-each=3 --trace=retain-on-failure   # flake check
PLAYWRIGHT_JSON_OUTPUT_NAME=.stack/out/tester/<stamp>-report.json npx playwright test tests/e2e/signup.spec.ts --reporter=line,json
# read failures from the JSON with jq; never run show-report / show-trace (interactive viewers that
# block unattended runs): list the report and trace paths under Files for the user
```

Rules:
- Assertions use web-first `expect(...)` (auto-waiting); no `waitForTimeout`.
- One behaviour per test; independent tests (no ordering).
- A failing test for a bug is written first and must fail for the right reason before the fix.
- Never weaken an assertion to make a test pass; a wrong expectation is changed only with evidence
  that the spec, not the code, was wrong.

## Evidence block for a report

```markdown
| # | Step | Expected | Actual | Evidence |
|---|---|---|---|---|
| 1 | open /signup | heading "Create account" | ok | snapshot e5 |
| 2 | submit valid form | heading "Welcome", URL /dashboard | 500 from POST /api/users | network #14 status 500; console "TypeError: ..."; .stack/out/tester/20261019-1412-step2.png |
Flake check: 3/3 failed (deterministic). Trace: .stack/playwright/trace-20261019-1413.zip
```
