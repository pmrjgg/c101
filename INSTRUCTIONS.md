I'll check the installer's actual options rather than guess.

I'll do a dry run of the full install command to show exactly what it would change.

Careful: that last command printed "enabled firecrawl" with no `[dry-run]` prefix. `--dry-run` has to come before the action, so it may have actually changed `.mcp.json`. Checking:

Oops—that command modified `.mcp.json` and `.claude/settings.json`, which were both clean before. I'll check the settings diff and then restore both files.

I briefly modified your project config by mistake, and it's restored. I dry-ran `bin/stack mcp enable firecrawl` with `--dry-run` placed after the action; that command only honours it before the action, so it really added firecrawl to `.mcp.json` and `.claude/settings.json`. Both files were clean beforehand, so I restored them with `git checkout`, and the working tree is clean again. The installer dry-run itself changed nothing.

## The full install command

`--packs all` is already the default with `--user`; it's spelled out here for clarity:

```bash
./install.sh --user --main-agent --enforce-models --packs all
```

The dry-run confirms what it does:
- **Python:** installs Python 3.13 and the dependencies through uv, and creates the `~/.claude/stack.env` template (mode 600).
- **Everything, in every project:** links all 57 agents, 228 skills (all 19 packs) and 8 saved workflows into `~/.claude/`.
- **Hooks and settings:** writes the stack's hooks, depth and environment settings into `~/.claude/settings.json`, keeping a backup.
- **`--enforce-models`:** only the three tier models (Opus 5.5, Sonnet 5.5, Haiku 5.5) are allowed anywhere.
- **`--main-agent`:** a plain `claude` starts with the delegator as the main thread.
- **MCP servers:** all 9 stack servers (exa, jina, spider, context7, fetch, image, desktop-sandbox, neural-memory, playwright) need no registration. They load lazily inside the agents that use them.

To preview first, add `--dry-run` anywhere on this command.

## Then, to switch on every feature

```bash
$EDITOR ~/.claude/stack.env
```

Add your keys, and merge in the `IMAGE_*` lines from `config/stack.env.fal.example` with your fal key.

```bash
bin/stack keys
```

```bash
bin/stack doctor
```

```bash
bin/desktop-sandbox --build --profile recommended
```

That builds the sandboxed computer-use image (Docker or podman required). Finally, in Claude Code, accept the folder-trust prompt once and run `/mcp` → computer-use → Enable to turn on computer use for your real Mac desktop.

## Optional third-party MCP servers

These aren't part of "all", by design: firecrawl, tavily, brave-search, markitdown, fal's own hosted server, recraft, flux, replicate, runware and peekaboo. Each needs its own key or OAuth. Enabling one adds it to the project's `.mcp.json`, so it connects in every session and its tools take context. The image server already covers fal, so I'd enable only the ones you'll actually use, one at a time, with `--dry-run` first and **before** the action:

```bash
bin/stack mcp --dry-run enable tavily
```

```bash
bin/stack mcp enable tavily
```

One reminder: commit `3768bcf` still needs `git push origin main` from your terminal.