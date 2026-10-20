# GUI testing in the desktop sandbox (tester)

Use the sandbox for GUI checks of the user's own desktop app when unit and integration tests cannot see
the defect: layout, focus order, keyboard paths, dialogs, rendering, crash on interaction. Web apps stay
with Playwright.

## 1. Make the app runnable inside

| App kind | How it gets in | Image needs |
|---|---|---|
| Linux binary or AppImage-extracted tree | build on the host or in CI for linux/amd64 or arm64 to match the runtime, then `put_file` the binary | its shared libraries via `--packages` (check with `ldd` in a build container) |
| JVM (Swing or JavaFX) | `put_file` the jar | `openjdk-17-jre` (plus `openjfx` for JavaFX) |
| Python Tk, Qt or GTK | `put_file` the script or wheel | `python3-tk` / `python3-pyqt6` / `python3-gi gir1.2-gtk-4.0` |
| Electron | `put_file` the packed linux app directory as one archive, plus a launcher the image provides | `libnss3 libgbm1 libasound2`; launch with `--no-sandbox` only inside this container (the container is the sandbox) |

`put_file` copies one file. For a directory, archive it into the project's build output (`tar czf build/app.tgz -C build app`; `.stack/`, `.git/` and `.claude/` are refused as sources)
and unpack inside: `launch {argv: ["tar", "xzf", "/exchange/app.tgz", "-C", "/exchange"]}`. If the image
lacks something, return an Open doubt with the exact rebuild command (`bin/desktop-sandbox --build --profile recommended --packages "..."`). The `tester` profile already has OpenJDK 17, Python Tk, PyQt6, GTK 3 bindings and the Electron libraries. Never request network
to fetch it.

## 2. Deterministic waits

- After `launch`, poll `window_list` (cheap text) until the expected title appears, up to about 10 s in
  `wait {seconds: 1, then_screenshot: false}` steps. Never use fixed long sleeps.
- After an action, use `then_screenshot: true`, which settles for 0.4 s before capturing. Animations
  may need one `wait`.
- Disable animations and blinking cursors in the app under test if it has a flag; it removes most
  screenshot diffs.

## 3. Assertions

| Check | How |
|---|---|
| Window appeared or closed, title changed | `window_list`: titles and geometry (text; untrusted but authored by the app under test) |
| Value or label shows X | `zoom` on the region, read it, and state the exact string observed |
| Layout not clipped at small sizes | `key alt+F8` (openbox resize) or the app's own size flag; screenshot at 1280x800 and at a `DESKTOP_SANDBOX_SIZE` the user set |
| File produced | app saves to `/exchange/...`; assert on the host with Bash (`test -s`, `file`, content diff) |
| No crash | `window_list` still shows the window after the step; for stderr, launch through `sh -c` only if the image's shell is needed: `["sh", "-c", "/exchange/app 2>/exchange/app.err"]` (a shell inside the sandbox is fine; it is still contained) |
| Visual regression | `screenshot {save: true}` per checkpoint; compare with Pillow `ImageChops.difference` against a baseline in `.stack/out/tester/` and report the bounding box of any difference |

Every test claim names its evidence: a saved screenshot path, the zoomed text, or the Bash output.

## 4. Proving the test can fail

Same rule as every tester check. Break the behaviour (revert the fix, feed the bug input) and show the
GUI check fails in the sandbox, then restore and show it passes three times in a row.

## 5. Codify it

The exploratory run is not the deliverable. Leave a repeatable test:

- Prefer the app toolkit's own test harness when one exists (pytest-qt, TestFX, AssertJ-Swing, Tk
  `event generate`). The sandbox run proves the scenario; the harness keeps it.
- Otherwise write a plain xdotool script under the project's test directory that mirrors the step log
  (`xdotool search --sync --name '^MyApp' windowactivate`, `xdotool key ctrl+s`, ...), plus a
  `run-in-xvfb` CI recipe (`xvfb-run -a ./gui_smoke.sh`). Write it with your file tools in the project;
  the sandbox never writes outside `/exchange`.

## 6. Flake control

| Flake source | Fix |
|---|---|
| Timing | poll `window_list` or a file, never fixed sleeps |
| Fonts and anti-aliasing in diffs | same image tag for baseline and run; compare with a small tolerance |
| Focus stolen by a dialog | `window_list` first, then `click` the window title bar before typing |
| Leftover state | every run starts from a fresh `sandbox_start`; nothing persists outside `/exchange` |
