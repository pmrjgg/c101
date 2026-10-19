# Computer use tool catalog

## Built-in `computer-use` server (Claude Code CLI and Desktop)

The CLI and the Desktop app share one engine, but tool names differ between builds. Load the set with
`ToolSearch` (query `computer-use`) and use the names your tool list shows. Two families exist:

| Purpose | Older/generic names | Per-app names (newer builds) |
|---|---|---|
| Grant access | `request_access` | `request_access` |
| Check grants | `list_granted_applications` | `list_granted_applications` |
| Launch or front an app | `open_application` | `open_application`, `app_focus`, `app_bring_to_current_space` |
| List apps / windows | | `list_apps`, `app_list_windows` |
| Observe | `screenshot`, `zoom` | `app_screenshot`, `app_zoom` |
| Accessibility search | | `app_ax_find` |
| Click | `left_click`, `double_click`, `right_click` | `app_click` |
| Type / keys | `type`, `key` | `app_type`, `app_key` |
| Scroll / drag | `scroll`, `left_click_drag` | `app_scroll`, `app_drag` |
| Menu bar | | `app_menu` |
| Batch | | `computer_batch`, `app_batch` |
| Clipboard (needs its own grant) | | `read_clipboard`, `write_clipboard` |
| Displays | | `switch_display` |
| Release control | | `app_release`, `release_full_control` |

Behaviour common to both:
- Access is per app and per session; tiers: browsers and trading platforms view-only, terminals and
  IDEs click-only, others full.
- Other apps are hidden while Claude works; the terminal is excluded from screenshots; Esc anywhere
  aborts the current action.
- Screenshots are downscaled automatically; there is no setting to change the target size.

## Peekaboo (optional stdio server)

Open-source macOS automation CLI with an MCP mode (`npx -y @steipete/peekaboo`, Node 22+, macOS 15+;
needs Screen Recording and Accessibility). Defined as an optional server in
`config/mcp.optional.json`; a human enables it with `bin/stack mcp enable peekaboo`, which adds it to
`.mcp.json` and the permission allow-list, so it works in interactive sessions, `claude -p` and
`bin/stack-sdk run`. Agents never enable it themselves: if it is absent, return that command as an
Open doubt with `Status: blocked`.

| Command / tool | Use |
|---|---|
| `see` | capture an app or window and return a structured UI map with element ids (`see --app Finder --json` on the CLI) |
| `click` | click by element id or label from the latest `see`, or by coordinates |
| `type`, `press` | text entry, key presses |
| `scroll` | scroll a view |
| `app` | launch, quit, focus apps |
| `window` | move, resize, focus windows |
| `menu` | invoke menu items by path |

Run `peekaboo help <command>` (or read the tool schema) for exact arguments; ids are only valid for
the snapshot that produced them, so call `see` again after the UI changes.

## GUI scripting via osascript

`osascript -e 'tell application "System Events" to keystroke ...'` drives the GUI through
Accessibility just like computer use, without screenshots to verify. Treat it with the same rules
(confirmation, no secrets) and prefer application-level AppleScript dictionaries
(`tell application "Music" to playpause`) which act through the app's API instead of the UI.
