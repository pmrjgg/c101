# Web content safety (prompt injection)

Pages, search results and documents fetched from the web are untrusted: a page can carry text written for an AI
agent ("ignore previous instructions", "send the API keys to …", fake tool-call markup, hidden characters). The
stack contains this in three layers, configured in `config/policy.json` `web_content` and implemented in
`stack/injection.py` and two hooks.

| Layer | Mechanism | Effect |
|---|---|---|
| 1. Narrow tools | `web_agents` (the research agents, `file-summarizer`, `browser-operator`, `computer-operator`) have `disallowedTools: [Edit, NotebookEdit]`; the `pre-tool` hook (PreToolUse on `Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`) | files only under `.stack/`; Bash network egress, pipe-to-shell, secret reads, `git push` and recursive deletes outside `.stack/` are denied, always, so a successful injection has little to work with |
| 2. Scanner | the `post-web` hook (PostToolUse on `WebFetch`, `WebSearch` and the `fetch`, `jina`, `exa`, `spider`, `playwright`, `firecrawl`, `tavily`, `brave-search`, `markitdown` tools) scores the result with weighted rules | score ≥ 3 (`medium`): a warning with the URL and matched rules is added to the agent's context, the agent is tainted and the event is logged to `<data>/injection.jsonl` (rule names, score, URL and a SHA-256 of the content, never the text); score ≥ 6 (`high`): also a `block` decision with the reason |
| 3. Taint guard | `pre-tool` and `pre-agent` check `<data>/sessions/<session>.taint.json` | a tainted subagent's risky actions are denied (the main thread gets an `ask` prompt instead), including typing into or uploading to web pages; it may only spawn `tainted_may_spawn` (`@research_leaves`, all narrow-tool agents) |

Rules (weights): instruction override (4), tool-call markup (4), requests to send secrets (4), ASCII smuggling
with Unicode tag characters (4), text addressed to an AI (3), "new instructions:" (3), exfiltration-shaped URLs
(3), persona switches (3), secrecy demands (3), chat-template tokens or role tags (2), secret paths (2),
pipe-to-shell snippets (2) and runs of zero-width characters (2). Text is NFKC-normalised and zero-width
characters are removed before matching, so split words are caught. Weak signals alone (an install page with
`curl … | sh`, documentation showing `<|im_start|>`) stay below `medium`.

Limits: these are tripwires, not a guarantee. Paraphrases, other languages and text inside images get through,
which is why layer 1 applies whether or not anything was flagged. Cost: about 50 ms per guarded tool call and
about 95 ms per 200 KB page scanned. Turn the whole feature off with `web_content.enabled: false`; tune
`medium`, `high`, `web_agents` and `tainted_may_spawn` in the same block. Tests: `tests/test_injection.py`.
