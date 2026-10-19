# Playwright MCP tool catalog

From the `microsoft/playwright-mcp` README (October 2026). `?` = optional. `target` is the element
reference from the latest snapshot; older releases call it `ref`. `element` is a human-readable
description used for permission prompts and logs. Always confirm against the live schema: the stack
runs `@latest`.

## Core (always on)

| Tool | Params | Notes |
|---|---|---|
| `browser_navigate` | `url` | waits for load |
| `browser_navigate_back` | none | |
| `browser_snapshot` | `target?`, `filename?`, `depth?`, `boxes?` | accessibility tree with refs; `filename` writes to disk; `depth` limits size |
| `browser_click` | `element?`, `target`, `doubleClick?`, `button?`, `modifiers?` | |
| `browser_type` | `element?`, `target`, `text`, `submit?`, `slowly?` | `slowly` types per key |
| `browser_fill_form` | `fields` | each field: name, type (textbox, checkbox, radio, combobox, slider), target, value |
| `browser_select_option` | `element?`, `target`, `values` | |
| `browser_hover` | `element?`, `target` | menus revealed on hover |
| `browser_drag` | start and end element + target | |
| `browser_press_key` | `key` | `Enter`, `Escape`, `ArrowDown`, `Control+a` |
| `browser_wait_for` | `time?` (max 30 s), `text?`, `textGone?` | prefer text conditions |
| `browser_take_screenshot` | `element?`, `target?`, `type?`, `filename?`, `fullPage?`, `scale?` | png or jpeg |
| `browser_evaluate` | `element?`, `target?`, `function`, `filename?` | `"() => ..."` or `"(el) => ..."` with a target |
| `browser_find` | `text?` or `regex?`, `filename?` | locate elements without a full snapshot |
| `browser_network_requests` | `static?`, `filter?`, `filename?` | `static: false` hides images, fonts, CSS |
| `browser_network_request` | `index`, `part?`, `filename?` | one request's details/body (newer builds) |
| `browser_console_messages` | `level?`, `all?`, `filename?` | `level: "error"` for failures |
| `browser_handle_dialog` | `accept`, `promptText?` | |
| `browser_file_upload` | `paths?` | absolute paths; omit to cancel the chooser |
| `browser_tabs` | `action` (list, new, close, select), `index?`, `url?` | |
| `browser_resize` | `width`, `height` | responsive checks |
| `browser_close` | none | ends the isolated session |
| `browser_run_code_unsafe` | `code?`, `filename?` | arbitrary code in the server process: avoid |

## vision cap (enabled)

`browser_mouse_click_xy {x, y, button?, clickCount?, delay?}`, `browser_mouse_move_xy`,
`browser_mouse_drag_xy`, `browser_mouse_wheel`. Coordinates come from the latest screenshot. Use for
canvas, maps, charts; anything with a ref should use the ref.

## pdf cap (enabled)

`browser_pdf_save {filename?}`.

## devtools cap (enabled)

`browser_start_tracing` / `browser_stop_tracing` (trace zip in the output dir),
`browser_start_video {filename?, size?, fps?, cursor?}` / `browser_stop_video`, plus highlighting,
annotation and recording helpers in recent builds (`browser_annotate`, `browser_start_recording`,
`browser_stop_recording`, `browser_resume`). List trace files under Files; the user opens them with `npx playwright show-trace <file>` (an interactive viewer agents never run).

## testing cap (NOT enabled in this stack)

`browser_verify_element_visible {role, accessibleName}`, `browser_verify_text_visible {text}`,
`browser_verify_list_visible {element, target, items}`, `browser_verify_value {type, element, target,
value}`, `browser_generate_locator {element?, target}`. If you need them, ask the caller to add
`testing` to `--caps` in `.mcp.json`; until then assert via snapshot, `browser_find`,
`browser_evaluate`.

## network and storage caps (NOT enabled)

Route mocking, offline mode, cookies and local/session storage tools, storage-state save/restore.
Not available here; for mocking write a `@playwright/test` spec with `page.route` instead.

## Server flags worth knowing

- `--isolated`: in-memory profile; `--storage-state <file>` can seed state (not configured here).
- `--allowed-origins` / `--blocked-origins`: convenience filters, not a security boundary, and they do
  not apply to redirects.
- `--secrets <dotenv file>`: masks matching values in tool output; a convenience, not protection.
  Never rely on it to make entering secrets acceptable.
