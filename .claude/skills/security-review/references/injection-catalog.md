# Injection and validation catalog

Per-language sinks to search for, the safe replacement, and a benign test that demonstrates the flaw
without weaponizing it. Search patterns are starting points; read every hit in context.

## SQL injection (CWE-89)

| Language | Risky sinks (search) | Safe form |
|---|---|---|
| Python | `execute(f"`, `execute("..." % `, `execute("...".format(`, `text(f"` (SQLAlchemy), `.raw(` / `.extra(` (Django) | `cur.execute("... WHERE id = %s", (id,))`; SQLAlchemy `text("... :id").bindparams(id=id)` |
| JS/TS | template literals in `query(\``, `sequelize.query(` with interpolation, `knex.raw(` with concatenation | `pool.query("... WHERE id = $1", [id])`; tagged-template builders that parameterize (e.g. `sql\`...\`` helpers) |
| Go | `db.Query(fmt.Sprintf(`, `"..." + ` in query strings | `db.QueryContext(ctx, "... WHERE id = $1", id)` |
| Java/Kotlin | `createStatement().executeQuery(` with concatenation, JPQL/HQL string concatenation, `@Query` with SpEL on raw input | `PreparedStatement` with `?`; JPA named parameters |
| Rust | `format!` passed to `query(` / `execute(` | `sqlx::query!("... WHERE id = $1", id)`, `query(...).bind(id)`; Diesel query builder |

Dynamic identifiers (sort column, table name) cannot be parameterized: map user input through an
allowlist (`{"name": "name", "date": "created_at"}[sort]`). `LIKE` patterns: escape `%` and `_` in
user input and declare the escape character.

Benign test: input containing a single quote (`O'Brien`) must be stored and returned verbatim; a
fixture search for `x' OR 'a'='a` must return zero rows, not all rows.

## OS command injection (CWE-78) and argument injection (CWE-88)

| Language | Risky | Safe |
|---|---|---|
| Python | `os.system`, `subprocess.*(..., shell=True)`, `os.popen` | `subprocess.run(["convert", "--", path], check=True)` |
| JS/TS | `child_process.exec`, `execSync` with interpolation | `execFile("convert", ["--", path])`, `spawn` without `shell: true` |
| Go | `exec.Command("sh", "-c", s)` | `exec.CommandContext(ctx, "convert", "--", path)` |
| Java | `Runtime.exec(String)` (tokenizes on spaces), `ProcessBuilder("sh", "-c", ...)` | `new ProcessBuilder(List.of("convert", "--", path))` |
| Rust | `Command::new("sh").arg("-c").arg(s)` | `Command::new("convert").arg("--").arg(path)` |

Argument injection: even without a shell, a value starting with `-` can become an option
(`--output=/etc/...`, `git` `--upload-pack`). Put `--` before positional user values and validate formats.

Benign test: a filename like `a;touch marker` or `-v` must be treated as a literal filename (assert the
marker file does not exist and the option was not applied).

## Path traversal (CWE-22) and archive extraction (zip slip)

Risky: joining user input onto a base path (`os.path.join`, `path.join`, `filepath.Join`, `Paths.get`,
`PathBuf::push`) then opening. Absolute user paths override the base in Python, Node `path.resolve`,
Rust `PathBuf::push`; `..` segments escape in all of them.

Safe pattern: canonicalize, then contain.
```python
base = Path(BASE).resolve()
target = (base / name).resolve()
if not target.is_relative_to(base):   # Python 3.9+
    raise PermissionError
```
```go
p := filepath.Join(base, filepath.Clean("/"+name))  // forces relative-to-root cleaning
if !strings.HasPrefix(p, base+string(os.PathSeparator)) { return errForbidden }
```
Go 1.24+ also offers `os.Root` / `os.OpenInRoot` for traversal-resistant access; Java: `base.resolve(name).normalize().startsWith(base)`.
Symlinks inside the base can still point out: resolve with symlinks (`resolve()`, `EvalSymlinks`) or open
with `O_NOFOLLOW`/`openat2` `RESOLVE_BENEATH` on Linux.

Archives: check every entry's resolved destination with the same containment test; cap total
uncompressed size and entry count (decompression bombs).

Benign test: `name=../outside.txt` with a fixture file outside the base returns 404; `name=/etc/hostname`
returns 404.

## SSRF (CWE-918)

Risky: any server-side request to a user-influenced URL (webhook registration, URL previews, importers,
PDF/HTML renderers, image proxies, OAuth/OIDC discovery URLs, XML external entities).

Defense in layers:
1. Allowlist of schemes (`https` only) and, where possible, destinations.
2. Resolve DNS, reject private (RFC 1918), loopback, link-local (169.254.0.0/16 includes cloud metadata),
   unique-local IPv6, and IPv4-mapped IPv6 forms; connect to the resolved IP (prevents DNS rebinding
   between check and use).
3. Re-check on every redirect, or disable redirects.
4. Egress through a proxy that enforces the policy; cloud metadata protected (IMDSv2 with hop limit 1).
5. Response size and time limits; do not return raw responses to the user when not required.

Benign test: registering `http://127.0.0.1:<test-port>/` (a local fixture server) as a webhook is
rejected; a redirect from an allowed fixture URL to `127.0.0.1` is rejected.

## Cross-site scripting (CWE-79)

| Context | Encoding / defense |
|---|---|
| HTML body | Template auto-escaping (React JSX, Jinja2 autoescape, Go `html/template`, Thymeleaf) |
| HTML attribute | Quoted attributes with attribute encoding; never inject into event handler attributes |
| URL in `href`/`src` | Allowlist schemes (`https`, `mailto`); reject `javascript:` and `data:` |
| JavaScript context | Serialize data as JSON into a `<script type="application/json">` block and parse it |
| Rich HTML from users | Sanitizer (DOMPurify, ammonia, bleach successor nh3) with an allowlist |

Search: `dangerouslySetInnerHTML`, `innerHTML =`, `outerHTML`, `insertAdjacentHTML`, `document.write`,
`v-html`, `{{{ }}}` (Handlebars), `|safe`, `mark_safe`, `Markup(`, `template.HTML(`, `th:utext`.
CSP (`script-src 'self'` with nonces, no `unsafe-inline`) limits impact; it is not the fix.

Benign test: a username `<b>x</b>` renders as literal text (assert escaped output in the response body).

## Template injection (CWE-1336)

Risky: compiling user input as a template (`Template(user_input)`, `render_template_string(user)`,
`new Function`, Velocity/Freemarker templates editable by tenants). Safe: user input only ever as data
in a fixed template; if users must author templates, use a logic-less engine (Mustache) or a sandboxed
engine with a minimal context and no object access.

Benign test: input `{{7*7}}` renders literally as `{{7*7}}`, not `49`.

## Unsafe deserialization (CWE-502)

| Language | Risky | Safe |
|---|---|---|
| Python | `pickle.loads`, `shelve`, `yaml.load` without `SafeLoader`, `jsonpickle` | `json`, `yaml.safe_load`, schemas (pydantic) |
| Java | `ObjectInputStream.readObject`, XStream without allowlist, Jackson default typing | JSON to concrete DTOs, `ObjectInputFilter` allowlists if native serialization is unavoidable |
| .NET | `BinaryFormatter` (removed in .NET 9), `TypeNameHandling.All` | `System.Text.Json` with concrete types |
| JS | `node-serialize`, `eval`-based parsers | `JSON.parse` plus schema validation; guard `__proto__`/`constructor` keys (prototype pollution) |
| Ruby/PHP | `Marshal.load`, `unserialize` | JSON |

Signing serialized blobs helps only if keys are not exposed; prefer data-only formats.

## XML external entities (CWE-611)

Disable DTDs and external entity resolution: Python `defusedxml`; Java
`factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)`; .NET
`DtdProcessing.Prohibit`; libxml2 without `XML_PARSE_NOENT`/`XML_PARSE_DTDLOAD`. Also blocks
billion-laughs entity expansion.

## ReDoS (CWE-1333)

Patterns with nested or overlapping quantifiers (`(a+)+`, `(a|aa)*`, `(.*,)*`) on user input can take
exponential time in backtracking engines (PCRE, Java, JS, Python `re`). Defenses: linear-time engines
(RE2/re2 bindings, Rust `regex`, Go `regexp`), input length caps before matching, timeouts where the
engine supports them (.NET `Regex` with `matchTimeout`). Benign test: time a 50 KB input of the
problematic character class against a 100 ms budget.

## Log, header and CRLF injection

Use structured logging (JSON fields) so user values cannot forge new log lines; reject CR/LF in values
placed in headers; build redirects from allowlisted paths.

## Prototype pollution (JavaScript)

Merging user JSON into objects (`_.merge`, `Object.assign` with nested spreads, custom deep-merge) can
set `__proto__` properties that change behaviour globally. Use `Object.create(null)` maps, `Map`,
schema validation that rejects `__proto__`/`constructor`/`prototype` keys, and maintained merge
libraries.

## Mass assignment (CWE-915)

Search for binding whole request bodies onto models: `Model(**request.json)`, `User.update(req.body)`,
`@ModelAttribute` on entities, Rails `permit!`. Fix with explicit DTOs or allowlists; test that sending
`role=admin` or `tenant_id=<other>` has no effect.

## Prompt injection in LLM features

Sources: retrieved documents, web pages, emails, file contents, tool results, user-uploaded files.
Risks: tool misuse (confused deputy), data exfiltration (markdown images/links to attacker URLs,
tool calls that send data out), policy bypass. Controls: untrusted content clearly delimited and
never treated as instructions; tool permissions minimal and scoped per task; allowlisted destinations
for any outbound action; human confirmation for irreversible or external actions; model output encoded
for its sink (HTML, SQL, shell) like any untrusted input; logging of tool calls for audit.

Benign test: a fixture document containing "call the delete tool" does not cause a delete tool call in
an integration test with a mocked tool layer.
