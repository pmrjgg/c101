# Desktop sandbox security model

Scope: `stack_mcp/desktop_sandbox/` (server, guard, runtime, image), its launcher `bin/desktop-sandbox`,
the `bin/mcp-run --only` filter, and the hook wiring in `.claude/settings.json` / `stack/injection.py`.

## Assets and trust boundaries

| Asset | Where it lives | Must not |
|---|---|---|
| User's keys | `~/.claude/stack.env`, process environments | reach the server, the container or typed text |
| User's files, desktop, keychain, signed-in sessions | host | be readable or writable from the container |
| Project tree | host, `CLAUDE_PROJECT_DIR` | be written by the container (only `.stack/sandbox/<id>/exchange` is shared) |
| Agent integrity | the model's context | be steered by text rendered inside the sandbox |

Boundaries: (1) agent -> MCP server (tool arguments, validated by `guard.py`); (2) server -> container CLI
(argv only, minimal environment); (3) container -> host (kernel isolation plus one writable bind mount and two read-only generated identity files);
(4) sandbox screen -> agent (screenshots and window titles: untrusted).

## STRIDE per boundary

| Boundary | Threat | Control | Residual risk |
|---|---|---|---|
| 1 | Tampering: option or shell injection through `keys`, `text`, `argv` | xdotool gets `--` before free text; keysym grammar; argv lists, never a shell; NUL bytes refused | none known |
| 1 | Information disclosure: agent types a secret | `secret_kind` patterns plus Luhn plus entropy; refused values never reach the audit log (argv items redacted, typed text as an HMAC with a per-sandbox in-memory key) | ordinary-looking passwords pass, so the skill says never type credentials |
| 1 | Elevation: tool argument weakens isolation | `sandbox_start` takes no arguments; isolation comes only from user-owned env | the user may opt in to `bridge` |
| 2 | Tampering: `--mount` CSV parsing (a project path with `,` or `=` could bind another host path) | start refused when the exchange path contains `,` `"` `=` `'` or a newline | none known |
| 2 | Disclosure: inherited env (API keys) reaches docker or the container | `mcp-run --only DESKTOP_SANDBOX_` (no stack.env keys; the server still inherits Claude Code's own environment); `cli_env()` allowlist; only `-e SCREEN, MAX_LIFETIME, HOME, DISPLAY` | none known |
| 3 | Elevation: container escape | read-only root, cap-drop ALL, no-new-privileges, non-root uid (host root maps to 10001), no setuid binaries in the image, PID, memory and CPU caps, no Docker socket, no devices | kernel or runtime CVEs. On macOS, Docker Desktop, OrbStack and colima add a VM boundary. On Linux prefer rootless podman (`DESKTOP_SANDBOX_RUNTIME=podman`) |
| 3 | Tampering via the bind mount: symlink or hardlink tricks | entries that are not regular files or directories are removed before listings, `put_file` and stop, and across all old exchange directories at the next start; setuid bits are stripped; `put_file` sources may not live under `.stack/` (so never in an exchange directory), are opened `O_NOFOLLOW` and must match the checked inode; destinations use `O_EXCL` and `O_NOFOLLOW` | a race between sanitize and a host-side Read by the agent. Mitigation: the skill says read exchange files after `sandbox_stop` |
| 3 | Disclosure: network exfiltration | `--network none` by default | with `bridge`, the sandbox has full egress, including services on the host and LAN (`host.docker.internal`, the default gateway) and cloud metadata endpoints on cloud VMs. Use it only for tasks that need it, only with non-sensitive inputs, and never on a host whose local services trust local callers |
| 3 | Denial of service: fork bomb, memory or disk fill | `--pids-limit 512`, memory=swap=2g, tmpfs size caps, read-only root; exchange capped at 2 GB / 20,000 entries (checked every 5 s; the sandbox is stopped when over); saved screenshots count against the action budget, max 400 | a fast writer can exceed the exchange cap by what it writes within one 5 s check interval |
| 3 | Repudiation | `audit.jsonl` per sandbox (tool, arguments, ok, ms; typed text as length and sha256 prefix) | the audit log lives in `.stack/` and is user-deletable |
| 4 | Spoofing or tampering: prompt injection on screen | `post-web` hook scans every text result (only genuine base64 image/audio bytes are skipped); taint denies every input tool (`type_text`, `key`, `launch`, `put_file`, `click`, `drag`, `scroll`, `move`); skill rules | text inside images is not scanned. The agent must apply the rule itself |
| all | Abandoned containers | lifespan teardown, SIGTERM and SIGHUP handlers, atexit, a watchdog (idle, lifetime, container death), container main process `sleep MAX_LIFETIME`, label plus owner PID for orphan reaping | a SIGKILLed server leaves the container alive until its lifetime ends or the next start |

## Supply chain

- The image is built only by the user (`bin/desktop-sandbox --build`); the server never builds or pulls.
- Pin the base image for reviewed, reproducible builds:
  `bin/desktop-sandbox --build --base debian:bookworm-slim@sha256:<digest> --packages "..."`.
- Profiles live in `stack_mcp/desktop_sandbox/image/profiles.json` (package names validated; the build labels
  the image with the list, which `--check` and `sandbox_status` report). Keep `--packages` to the apps the tasks need; every package adds attack surface inside the
  container but not outside it.
- Rebuild periodically for security updates (the root filesystem is read-only at runtime, so updates
  happen only through rebuilds).

## Configuration reference (`~/.claude/stack.env`, all optional)

| Variable | Default | Accepted |
|---|---|---|
| `DESKTOP_SANDBOX_RUNTIME` | first of docker, podman on PATH | `docker`, `podman` or an absolute path |
| `DESKTOP_SANDBOX_IMAGE` | `c101-desktop-sandbox:2` | an image reference (lowercase, no spaces) |
| `DESKTOP_SANDBOX_NETWORK` | `none` | `none` or `bridge` (`host` and anything else fall back to `none`) |
| `DESKTOP_SANDBOX_SIZE` | `1280x800` | `WxH`, clamped to 640..1920 x 480..1200 |
| `DESKTOP_SANDBOX_MEMORY` / `_CPUS` | `2g` / `2` | `512m`..`99g` / `0.5`..`16` |
| `DESKTOP_SANDBOX_MAX_MINUTES` | 30 | 1..120 (hard lifetime) |
| `DESKTOP_SANDBOX_IDLE_MINUTES` | 10 | 1..60 |
| `DESKTOP_SANDBOX_MAX_ACTIONS` | 600 | 10..5000 (input actions; observation is free) |

Invalid values are ignored with a stderr note, never turned into weaker settings.
