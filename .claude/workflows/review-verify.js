export const meta = {
  name: 'review-verify',
  description: 'Code review with adversarial verification: scope the target, one finder per dimension and shard (reviewer; security-auditor for security; code-optimizer for performance), dedup by file+line+summary, then three lens-specific adversarial-verifier passes per finding; a finding survives only if a majority of lenses confirm it (failed lenses make it inconclusive).',
  whenToUse: 'Reviewing a diff, git range, commit or path where false positives are costly and coverage matters: large PRs, risky changes (auth, concurrency, money, migrations), pre-release audits. args {target: git range | commit | path | "worktree", dimensions?: ["correctness","security","concurrency","performance","api-design","tests"], context?: intent or spec text, votes?: 3 (odd, max 5), minSeverity?: "minor", maxVerify?: 40, shardLines?: 1500, maxFinders?: 48, outFile?: path or false, runTag?}. For a small diff use the reviewer agent directly.',
  phases: [
    { title: 'Scope', detail: 'file-summarizer resolves the target to a file list with churn and base/head SHAs, excluding generated, vendored and lock files' },
    { title: 'Find', detail: 'one finder per dimension x shard; findings carry file:line, failure scenario, severity, fix and confidence' },
    { title: 'Dedup', detail: 'merge findings on the same file within 2 lines whose title or scenario overlap (token Jaccard >= 0.5); triage by severity and cap before verification' },
    { title: 'Verify', detail: 'adversarial-verifier per finding through 3 distinct lenses (correctness/security/performance + reproducibility + scope); survive only if a majority confirm, failed lenses make it inconclusive' },
    { title: 'Report', detail: 'file-summarizer writes the ranked confirmed findings, inconclusive and rejected lists to a markdown report' },
  ],
}

// ---------------------------------------------------------------------------
// Find -> Dedup -> Verify. Barrier after Find is justified (cross-finder dedup
// before paying for 3 verifiers per finding). Survival math runs in code.
// ---------------------------------------------------------------------------

const notes = []
function note(msg) { notes.push(msg); log(msg) }

function parseArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try { a = JSON.parse(a) } catch (e) { a = { target: a } }
    if (typeof a === 'string') a = { target: a }
  }
  return a && typeof a === 'object' && !Array.isArray(a) ? a : {}
}
const A = parseArgs(args)
const TARGET = typeof A.target === 'string' ? A.target.trim() : ''
if (!TARGET) {
  return {
    started: false,
    reason: 'args.target is required: a git range (main..feature, HEAD~3..HEAD, A...B), a commit, a path, or "worktree" for uncommitted changes',
    next: 'Run Workflow review-verify with args {target: "origin/main..HEAD", dimensions: ["correctness","security","concurrency"], context: "what the change is meant to do"}',
  }
}

function clampInt(v, lo, hi, dflt) {
  const n = Number(v)
  if (!Number.isFinite(n)) return dflt
  return Math.max(lo, Math.min(hi, Math.round(n)))
}
function slugify(s, max) {
  const n = max || 48
  const t = String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  if (t.length <= n) return t || 'review'
  const cut = t.slice(0, n)
  const at = cut.lastIndexOf('-')
  return (at >= n / 2 ? cut.slice(0, at) : cut).replace(/-+$/g, '') || 'review'
}
const STOP = new Set(['the', 'and', 'for', 'with', 'when', 'from', 'this', 'that', 'into', 'are', 'can', 'not', 'may', 'will', 'which', 'via', 'its', 'has', 'have', 'been', 'any', 'all', 'missing', 'issue', 'possible', 'potential'])
function tokens(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9_.%]+/g, ' ').split(' ').map(w => w.replace(/^\.+|\.+$/g, '')).filter(w => (w.length > 2 || /\d/.test(w)) && !STOP.has(w))
}
function jaccard(a, b) {
  const x = new Set(tokens(a)), y = new Set(tokens(b))
  if (!x.size && !y.size) return 1
  let inter = 0
  for (const w of x) if (y.has(w)) inter++
  return inter / (x.size + y.size - inter)
}
function cleanOpts(o) {
  const r = {}
  for (const k of Object.keys(o)) if (o[k] !== undefined && o[k] !== null && o[k] !== '') r[k] = o[k]
  return r
}
async function call(prompt, opts) {
  try {
    return await agent(prompt, cleanOpts(opts))
  } catch (e) {
    note(`${opts.label}: agent call failed (${String((e && e.message) || e).slice(0, 160)})`)
    return null
  }
}

const SEV = { nit: 1, minor: 2, major: 3, blocker: 4 }
const SEV_NAMES = ['nit', 'minor', 'major', 'blocker']
const VERDICTS = ['confirmed:reproduced', 'confirmed:derived', 'refuted:counterexample', 'refuted:failed-reproduction', 'refuted:out-of-scope', 'refuted:misattributed', 'refuted:unfalsifiable', 'refuted:insufficient']

const DIMENSIONS = {
  correctness: {
    agentType: 'reviewer',
    lenses: ['correctness', 'reproducibility', 'scope', 'correctness', 'reproducibility'],
    focus: 'boundary and off-by-one errors; null/None/nil, empty-collection and zero-value paths; inverted conditions and wrong operators; error results ignored or swallowed; partial failure leaving inconsistent state (writes without rollback, half-applied migrations); retries around non-idempotent operations; integer overflow, float precision, money as float; time zones, DST, wall clock vs monotonic clock; encoding and locale; state-machine transitions that skip validation; cleanup on early return (files, connections, locks, temp dirs).',
  },
  security: {
    agentType: 'security-auditor',
    lenses: ['security', 'reproducibility', 'scope', 'security', 'correctness'],
    focus: 'untrusted input reaching sinks without validation (SQL/NoSQL, shell, path traversal, template/HTML, SSRF, deserialization, regex DoS, XXE); missing or bypassable authentication and authorization on every new route, handler or job (IDOR, tenant isolation, privilege escalation); secrets in code, logs, error messages or URLs; crypto misuse (homemade crypto, ECB, static IVs, fast hashes for passwords, non-constant-time comparison); unsafe defaults (debug on, CORS *, TLS verification off); dependency and lockfile changes that add risk; unsafe/FFI blocks. Describe exposure and impact; never write a weaponised exploit.',
  },
  concurrency: {
    agentType: 'reviewer',
    lenses: ['correctness', 'reproducibility', 'scope', 'correctness', 'reproducibility'],
    focus: 'data races on shared mutable state (handlers, singletons, caches, globals, closures captured by goroutines/tasks); check-then-act and read-modify-write without atomicity; lock ordering and deadlock; locks held across I/O or await points; blocking calls on async executors or event loops; missing cancellation, timeouts and context propagation; goroutine/task/thread leaks; unbounded queues and channels; memory ordering of atomics; double close or use after close; retry storms and thundering herds. Prefer race-detector or stress-loop evidence (go test -race -count=200, cargo test with loom, TSan, pytest-repeat).',
  },
  performance: {
    agentType: 'code-optimizer',
    lenses: ['performance', 'reproducibility', 'scope', 'performance', 'correctness'],
    focus: 'algorithmic complexity on hot paths (nested loops over request-sized data, N+1 queries, repeated parsing or regex compilation); allocation and copying in loops; unbounded growth (caches, buffers, maps keyed by user input); synchronous I/O on hot paths; missing batching, pagination, indexes or streaming; lock contention; log volume on hot paths. Every finding needs a cost model with sizes (n, QPS, bytes) or a measurement; do NOT run long benchmarks here (the verifier measures); no micro-optimisation nits without numbers.',
  },
  'api-design': {
    agentType: 'reviewer',
    lenses: ['correctness', 'scope', 'reproducibility', 'correctness', 'scope'],
    focus: 'breaking changes to public signatures, wire formats, config keys, CLI flags, defaults and error types without versioning or migration; inconsistent naming and units; nullability and optional semantics; the error contract callers can match on; idempotency of mutating endpoints; pagination and ordering guarantees; internal types leaking into public surface; missing or misleading docs for new public API; backward and forward compatibility of persisted data and events.',
  },
  tests: {
    agentType: 'reviewer',
    lenses: ['correctness', 'reproducibility', 'scope', 'correctness', 'reproducibility'],
    focus: 'changed behaviour without a test that would fail on the old code; weakened, skipped or deleted assertions; tests that cannot fail (asserting on mocks, tautologies, swallowed exceptions); flakiness (sleeps, wall-clock time, ordering, shared state, real network); missing edge cases for the changed logic (empty, max, unicode, concurrent); mocks that hide integration bugs; snapshot updates accepted wholesale. A finding names the concrete input or mutation that the suite would not catch.',
  },
  'error-handling': {
    agentType: 'reviewer',
    lenses: ['correctness', 'reproducibility', 'scope', 'correctness', 'reproducibility'],
    focus: 'errors dropped, logged-and-continued where the caller needs to know, or wrapped without context; panics/exceptions crossing API boundaries; retries without backoff, jitter or a cap; missing timeouts; error messages leaking internals; inconsistent error types for the same failure; cleanup and compensation on failure paths.',
  },
  readability: {
    agentType: 'reviewer',
    lenses: ['scope', 'correctness', 'reproducibility', 'scope', 'correctness'],
    focus: 'names that lie about behaviour, functions doing several unrelated things, duplicated logic that will drift, dead code, misleading comments, magic numbers without units. Only report what will plausibly cause a future defect; severity is at most minor unless a misleading name hides a real bug.',
  },
}
const LENS_TEXT = {
  correctness: 'Does the claimed wrong output actually occur for some valid input on a reachable path? Hunt for the guard, invariant, type rule or caller contract that prevents it.',
  security: 'Is the input attacker-controlled, does it reach the sink unsanitised, and what privilege does the attacker need? Check upstream validation, framework escaping, parameterisation and authz middleware. No weaponised exploit; a minimal benign proof is enough.',
  performance: 'Is the effect measurable above noise at production-like sizes? Build the cost model with explicit sizes or a short micro-benchmark (criterion, go test -bench, JMH, pytest-benchmark, hyperfine); a constant-factor claim without numbers is refuted:insufficient.',
  reproducibility: 'Does it reproduce on a clean checkout of the target, deterministically or at a stated rate? Write the smallest failing test or script; for concurrency use the race detector or a stress loop.',
  scope: 'Is the defect introduced or exposed by this target rather than pre-existing and untouched, and does it contradict the stated intent? Use git diff, git log -L and git blame on the lines.',
}

// ---------------- configuration ----------------
let dims = Array.isArray(A.dimensions) && A.dimensions.length ? A.dimensions : ['correctness', 'security', 'concurrency', 'performance', 'api-design', 'tests']
dims = Array.from(new Set(dims.map(d => String(d).trim().toLowerCase().replace(/[\s_]+/g, '-')).filter(Boolean)))
if (!dims.length) { dims = ['correctness', 'security', 'concurrency', 'performance', 'api-design', 'tests']; note('dimensions were all empty; using the default six') }
for (const d of dims) if (!DIMENSIONS[d]) note(`dimension "${d}" is not built in; it is reviewed by reviewer with a generic brief and correctness/reproducibility/scope lenses`)
function dimCfg(d) {
  return DIMENSIONS[d] || { agentType: 'reviewer', lenses: ['correctness', 'reproducibility', 'scope', 'correctness', 'reproducibility'], focus: `defects in the "${d}" dimension as an experienced reviewer would define it; every finding needs a concrete failure scenario.` }
}
let VOTES = clampInt(A.votes, 1, 5, 3)
if (VOTES % 2 === 0) { VOTES += 1; note(`votes must be odd to avoid ties; using ${VOTES}`) }
const NEED = Math.floor(VOTES / 2) + 1
const MIN_SEV = SEV[A.minSeverity] ? A.minSeverity : 'minor'
const MAX_VERIFY = clampInt(A.maxVerify, 1, 200, 40)
const MAX_FILES = clampInt(A.maxFiles, 1, 2000, 200)
let MAX_FINDERS = clampInt(A.maxFinders, 1, 200, 48)
if (MAX_FINDERS < dims.length) { note(`maxFinders=${MAX_FINDERS} is below the ${dims.length} dimension(s); raised to ${dims.length} (one finder per dimension is the minimum)`); MAX_FINDERS = dims.length }
const SLUG = slugify(TARGET, 40)
const TAG = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + slugify(A.runTag, 24) : ''
const RUN_DIR = `.stack/out/review-verify/${SLUG}${TAG}`
const OUT_FILE = A.outFile === false ? null : (typeof A.outFile === 'string' && A.outFile.trim() ? A.outFile.trim() : `${RUN_DIR}/report.md`)
const CONTEXT = typeof A.context === 'string' ? A.context.trim().slice(0, 4000) : ''
log(`target ${TARGET}; dimensions ${dims.join(', ')}; ${VOTES} verifier lens(es) per finding, survive with >= ${NEED} confirming (failed lenses -> inconclusive); verify severity >= ${MIN_SEV}, at most ${MAX_VERIFY}`)

// ---------------- Scope ----------------
phase('Scope')
const SCOPE_SCHEMA = {
  type: 'object',
  properties: {
    kind: { type: 'string', enum: ['range', 'commit', 'path', 'worktree', 'unresolved'] },
    range: { type: 'string', description: 'the exact git range used for diffs, e.g. abc123..def456 or C^..C' },
    base: { type: 'string' },
    head: { type: 'string' },
    files: {
      type: 'array',
      items: {
        type: 'object',
        properties: { path: { type: 'string' }, added: { type: 'integer' }, removed: { type: 'integer' }, language: { type: 'string' } },
        required: ['path', 'added', 'removed'],
      },
    },
    excluded: { type: 'array', items: { type: 'string' } },
    total_changed_lines: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['kind', 'files'],
}
const scope = await call(
  `You are scoping a code review for the review-verify workflow (phase Scope). Read-only: change nothing except files under ${RUN_DIR}/ (mkdir -p it). Do not spawn subagents.
Target: \`${TARGET}\`

1. Decide what the target is:
   - git range ("A..B", "A...B") or a single commit: \`git rev-parse --verify --quiet "<rev>^{commit}"\` for each end; for a single commit C use the range C^..C; keep triple-dot (merge-base) semantics when given. Run \`git diff --numstat --find-renames <range>\` and record base and head SHAs. kind = range or commit.
   - an existing file or directory: \`git ls-files -- <path>\` (outside git: \`find <path> -type f\`) and \`wc -l\` per file; added = line count, removed = 0. kind = path.
   - "worktree", "HEAD" or "staged": \`git diff --numstat HEAD\` plus untracked files from \`git ls-files --others --exclude-standard\` (line counts as added). kind = worktree.
2. Exclude generated, vendored and lock files and binaries (vendor/, node_modules/, third_party/, dist/, build/, target/, *.min.js, *.map, *.lock, package-lock.json, pnpm-lock.yaml, go.sum, Cargo.lock, *.pb.go, *_pb2.py, *_generated.*, __snapshots__/, numstat "-" entries); list each in excluded.
3. Write the full command output to ${RUN_DIR}/scope.txt.
Return kind, range, base, head, files [{path, added, removed, language}], excluded, total_changed_lines. If the target does not resolve, return kind "unresolved" and the error in notes.`,
  { label: 'scope', phase: 'Scope', agentType: 'file-summarizer', schema: SCOPE_SCHEMA },
)
if (scope && scope.kind === 'unresolved') {
  return { started: false, reason: `target "${TARGET}" did not resolve: ${scope.notes || 'unknown error'}`, next: 'Pass an existing git range (git log --oneline to find SHAs), commit, path, or "worktree".', notes }
}
let files = []
let filesCut = 0
let scopeInfo = { kind: 'unknown', range: TARGET }
if (scope) {
  scopeInfo = { kind: scope.kind, range: scope.range || TARGET, base: scope.base || '', head: scope.head || '', excluded: scope.excluded || [], total_changed_lines: scope.total_changed_lines }
  const seen = new Set()
  for (const f of (scope.files || [])) {
    const p = String(f.path || '').trim().replace(/^\.\//, '')
    if (!p || seen.has(p)) continue
    seen.add(p)
    files.push({ path: p, added: Math.max(0, Number(f.added) || 0), removed: Math.max(0, Number(f.removed) || 0), language: f.language || '' })
  }
  if (!files.length) {
    return { started: true, completed: true, target: TARGET, scope: scopeInfo, confirmed: [], inconclusive: [], rejected: [], unverified: [], leads: [], stats: { files: 0 }, summary: 'Nothing to review: the target has no reviewable changed files.', notes }
  }
  if (files.length > MAX_FILES) {
    files.sort((a, b) => (b.added + b.removed) - (a.added + a.removed) || (a.path < b.path ? -1 : 1))
    const cut = files.slice(MAX_FILES)
    filesCut = cut.length
    files = files.slice(0, MAX_FILES)
    note(`scope: ${cut.length} lowest-churn file(s) over maxFiles=${MAX_FILES} are NOT reviewed: ${cut.slice(0, 20).map(f => f.path).join(', ')}${cut.length > 20 ? ' ...' : ''}`)
  }
} else {
  note('scope: scoping failed; each finder resolves the whole target itself (no sharding)')
}

// ---------------- shards ----------------
function makeShards(fs, lineBudget) {
  const sorted = fs.slice().sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
  const out = []
  let cur = [], lines = 0
  for (const f of sorted) {
    const w = Math.max(1, f.added + f.removed)
    if (cur.length && (lines + w > lineBudget || cur.length >= 30)) { out.push(cur); cur = []; lines = 0 }
    cur.push(f)
    lines += w
  }
  if (cur.length) out.push(cur)
  return out
}
const defaultBudget = scopeInfo.kind === 'path' ? 4000 : 1500
let lineBudget = clampInt(A.shardLines, 200, 100000, defaultBudget)
let shards = files.length ? makeShards(files, lineBudget) : [null]
while (shards.length > 1 && shards.length * dims.length > MAX_FINDERS && lineBudget < 1e7) {
  lineBudget = Math.ceil(lineBudget * 1.5)
  shards = makeShards(files, lineBudget)
}
if (lineBudget !== clampInt(A.shardLines, 200, 100000, defaultBudget)) note(`shards enlarged to ~${lineBudget} changed lines: ${dims.length} dimension(s) x ${shards.length} shard(s) for maxFinders=${MAX_FINDERS}`)
if (shards.length * dims.length > MAX_FINDERS) note(`${dims.length * shards.length} finders exceed maxFinders=${MAX_FINDERS}: shards hold at most 30 files each`)
log(`find: ${dims.length} dimension(s) x ${shards.length} shard(s) = ${dims.length * shards.length} finder(s)`)

// ---------------- Find ----------------
phase('Find')
const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string', description: 'repo-relative path' },
          line: { type: 'integer', description: 'first line of the defect in the NEW version' },
          end_line: { type: 'integer' },
          title: { type: 'string' },
          failure_scenario: { type: 'string', description: 'concrete inputs/state -> wrong output, crash, leak or exposure' },
          severity: { type: 'string', enum: SEV_NAMES },
          fix: { type: 'string' },
          evidence: { type: 'string' },
          confidence: { type: 'number', minimum: 0, maximum: 1 },
          pre_existing: { type: 'boolean' },
        },
        required: ['file', 'line', 'title', 'failure_scenario', 'severity', 'confidence'],
      },
    },
    coverage_note: { type: 'string', description: 'what you read, and anything you could not review' },
  },
  required: ['findings'],
}
function targetLine() {
  const parts = [`Target: ${TARGET}`]
  if (scopeInfo.kind && scopeInfo.kind !== 'unknown') parts.push(`kind ${scopeInfo.kind}`)
  if (scopeInfo.range && scopeInfo.range !== TARGET) parts.push(`diff range ${scopeInfo.range}`)
  if (scopeInfo.base) parts.push(`base ${scopeInfo.base}`)
  if (scopeInfo.head) parts.push(`head ${scopeInfo.head}`)
  return parts.join('; ')
}
const finderItems = []
for (const d of dims) shards.forEach((s, k) => finderItems.push({ dim: d, shard: s, k }))
const findRaw = await parallel(finderItems.map(it => () => {
  const cfg = dimCfg(it.dim)
  const shardTxt = it.shard
    ? it.shard.map(f => `${f.path} (+${f.added} -${f.removed}${f.language ? ', ' + f.language : ''})`).join('\n')
    : '(scope unavailable: resolve the target yourself with git diff --stat / git ls-files)'
  return call(
    `You are the ${it.dim} finder in the review-verify workflow (phase Find${shards.length > 1 ? ', shard ' + (it.k + 1) + ' of ' + shards.length : ''}). You are one of ${finderItems.length} independent finders and adversarial verification runs after you: do NOT spawn adversarial-verifier, do NOT run review-verify or any other saved workflow (the Workflow tool is main-thread only), and do not modify tracked files (scratch files only under .stack/out/). Read-only commands are fine: git diff, git show, git log -L, git blame, grep, and existing fast tests.

${targetLine()}
${CONTEXT ? 'Intent / spec of the change: ' + CONTEXT + '\n' : ''}Files in your shard:
${shardTxt}

How to read: for a range, \`git diff ${scopeInfo.range || TARGET} -- <file>\` plus enough surrounding code (callers, callees, tests, config) to judge behaviour; for a path, read the files and their tests.

Dimension: ${it.dim}. Look for: ${cfg.focus}

Report only real defects in the target; pre-existing issues only when blocker-severity, flagged pre_existing=true. For each finding:
- file (repo-relative) and line (NEW version, first line of the defect), end_line if it spans lines
- title (one line) and failure_scenario: concrete inputs or state -> wrong output, crash, leak or exposure. No scenario, no finding.
- severity: blocker (data loss, security breach, crash or corruption on a main path), major (wrong result on a realistic path, leak under load), minor (edge case, degraded behaviour, narrow trigger), nit (style, naming, docs)
- fix: the concrete change; evidence: what you read or ran (file:line of guards you checked, command output)
- confidence 0..1 that it is real
At most 25 findings; a few high-confidence findings beat many speculative ones. An empty list is the right answer for a clean shard.`,
    { label: `find:${it.dim}${shards.length > 1 ? ':s' + (it.k + 1) : ''}`, phase: 'Find', agentType: cfg.agentType, schema: FINDINGS_SCHEMA },
  )
}))
const failedFinders = []
const raw = []
findRaw.forEach((r, i) => {
  const it = finderItems[i]
  if (!r) { failedFinders.push(`${it.dim}${shards.length > 1 ? ':s' + (it.k + 1) : ''}`); return }
  for (const f of (r.findings || [])) {
    const file = String(f.file || '').trim().replace(/^\.\//, '').replace(/^[ab]\//, '')
    const line = Number(f.line)
    if (!file || !Number.isFinite(line) || !String(f.failure_scenario || '').trim()) continue
    raw.push({
      file, line: Math.max(0, Math.round(line)), end_line: Number.isFinite(Number(f.end_line)) ? Math.round(Number(f.end_line)) : undefined,
      title: String(f.title || '').trim(), failure_scenario: String(f.failure_scenario).trim(), severity: SEV[f.severity] ? f.severity : 'minor',
      fix: f.fix || '', evidence: f.evidence || '', confidence: Math.min(1, Math.max(0, Number(f.confidence) || 0)), pre_existing: !!f.pre_existing,
      dims: [it.dim], reported_by: 1,
    })
  }
})
if (failedFinders.length) note(`find: ${failedFinders.length} finder(s) failed, coverage incomplete for: ${failedFinders.join(', ')}`)
const malformed = findRaw.filter(Boolean).reduce((t, r) => t + (r.findings || []).length, 0) - raw.length
if (malformed > 0) note(`find: dropped ${malformed} finding(s) without file, line or failure scenario`)

// ---------------- Dedup (barrier) ----------------
phase('Dedup')
raw.sort((a, b) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0) || (a.line - b.line) || (SEV[b.severity] - SEV[a.severity]) || (b.confidence - a.confidence))
const merged = []
for (const f of raw) {
  const hit = merged.find(m => m.file === f.file && Math.abs(m.line - f.line) <= 2 &&
    (jaccard(m.title, f.title) >= 0.5 || jaccard(m.failure_scenario, f.failure_scenario) >= 0.5))
  if (hit) {
    for (const d of f.dims) if (!hit.dims.includes(d)) hit.dims.push(d)
    hit.reported_by += 1
    if (SEV[f.severity] > SEV[hit.severity]) hit.severity = f.severity
    hit.confidence = Math.max(hit.confidence, f.confidence)
    if (f.failure_scenario.length > hit.failure_scenario.length) { hit.failure_scenario = f.failure_scenario; hit.title = f.title || hit.title }
    if (!hit.fix && f.fix) hit.fix = f.fix
    hit.evidence = [hit.evidence, f.evidence].filter(Boolean).join(' | ').slice(0, 1200)
    hit.pre_existing = hit.pre_existing && f.pre_existing
  } else {
    merged.push(Object.assign({}, f))
  }
}
merged.forEach((f, i) => { f.id = 'F' + (i + 1) })
log(`dedup: ${raw.length} raw finding(s) -> ${merged.length} unique`)

if (!merged.length) {
  return {
    started: true, completed: failedFinders.length < finderItems.length, coverage_complete: finderItems.length > 0 && failedFinders.length === 0 && filesCut === 0,
    target: TARGET, scope: Object.assign({}, scopeInfo, { files: files.length, shards: shards.length }),
    confirmed: [], inconclusive: [], rejected: [], unverified: [], leads: [],
    stats: { finders: finderItems.length, failed_finders: failedFinders, raw: raw.length, unique: 0, verified: 0, confirmed: 0 },
    summary: failedFinders.length === finderItems.length ? 'Every finder failed; nothing was reviewed.' : (failedFinders.length ? 'No findings, but some finders failed; coverage is incomplete.' : 'No findings in any dimension.'),
    notes,
  }
}

// Triage: severity floor, then cap by severity, confidence and agreement across dimensions.
const unverified = []
const eligible = []
for (const f of merged) {
  if (SEV[f.severity] < SEV[MIN_SEV]) unverified.push(Object.assign({}, f, { below_floor: true, reason: `below minSeverity=${MIN_SEV}; not verified` }))
  else eligible.push(f)
}
eligible.sort((a, b) => (SEV[b.severity] - SEV[a.severity]) || (b.reported_by - a.reported_by) || (b.confidence - a.confidence) || (a.file < b.file ? -1 : 1))
const toVerify = eligible.slice(0, MAX_VERIFY)
for (const f of eligible.slice(MAX_VERIFY)) unverified.push(Object.assign({}, f, { reason: `over maxVerify=${MAX_VERIFY}; not verified` }))
if (unverified.length) note(`triage: ${unverified.length} finding(s) not verified (${merged.length - eligible.length} below ${MIN_SEV}, ${Math.max(0, eligible.length - MAX_VERIFY)} over the cap); listed as unverified, never as confirmed`)

// ---------------- Verify ----------------
phase('Verify')
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: VERDICTS },
    restatement: { type: 'string', description: 'the falsifiable proposition you tested' },
    evidence: { type: 'string', description: 'decisive evidence: command + output excerpt, file:line of a guard, counterexample' },
    severity: { type: 'string', enum: SEV_NAMES, description: 'your independent severity reassessment' },
    true_cause: { type: 'string', description: 'for refuted:misattributed: the real cause and location' },
    settling_check: { type: 'string', description: 'for refuted:insufficient: the check that would settle it' },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['verdict', 'restatement', 'evidence', 'severity'],
}
// A merged finding takes the lens set of its most specialised dimension.
const LENS_PRIORITY = ['security', 'performance', 'concurrency', 'correctness', 'error-handling', 'api-design', 'tests', 'readability']
function lensesFor(f) {
  const ranked = f.dims.slice().sort((a, b) => {
    const ia = LENS_PRIORITY.indexOf(a), ib = LENS_PRIORITY.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
  return dimCfg(ranked[0]).lenses.slice(0, VOTES)
}
const decided = await pipeline(
  toVerify,
  async (f) => {
    const lenses = lensesFor(f)
    const votes = await parallel(lenses.map((lens, j) => () => call(
      `Try to REFUTE one code-review finding (review-verify workflow, phase Verify, lens ${lens}). Stay inside your lens. Default to refuted:insufficient when you cannot settle it: a plausible story is not evidence. Do not run workflows; do not modify tracked files (repro files only under .stack/out/adversarial-verifier/); clean up any process you start.

${targetLine()}
${CONTEXT ? 'Intent / spec: ' + CONTEXT + '\n' : ''}Finding ${f.id} [${f.severity}] ${f.title}
Location: ${f.file}:${f.line}${f.end_line ? '-' + f.end_line : ''}
Claimed failure scenario: ${f.failure_scenario}
Claimed fix: ${f.fix || 'none given'}
Finder evidence: ${f.evidence || 'none given'}
Raised by dimension(s): ${f.dims.join(', ')}${f.pre_existing ? ' (flagged pre-existing)' : ''}

Lens ${lens}: ${LENS_TEXT[lens]}
Procedure: restate the claim as a falsifiable proposition; read the code at the location and the guards around it (callers, validation upstream, types, config); then reproduce with the smallest script or test you can (for example go test -run X -race -count=50, pytest -k X, cargo test X, npm test -- -t X) or derive the failing path step by step.
Verdicts: confirmed:reproduced (deterministic reproduction at the target), confirmed:derived (independent derivation plus a reachable path shown step by step), refuted:counterexample (a guard, type rule, config or input shows it false), refuted:failed-reproduction (reproduction attempted, failure did not occur), refuted:out-of-scope (true but pre-existing or outside the target), refuted:misattributed (symptom real, cause or location different, or only a narrower claim survives: give true_cause / the narrowed claim), refuted:unfalsifiable, refuted:insufficient (give settling_check). These schema labels replace SURVIVES/REFUTED/NARROWED here: SURVIVES reproduced -> confirmed:reproduced; SURVIVES derivation-agrees or source-confirms -> confirmed:derived; REFUTED guarded-elsewhere, counterexample or precondition-false -> refuted:counterexample; NARROWED -> refuted:misattributed; insufficient-evidence -> refuted:insufficient. Reassess severity independently of the finder.`,
      { label: `verify:${f.id}:${lens}${j >= 3 ? j : ''}`, phase: 'Verify', agentType: 'adversarial-verifier', schema: VERDICT_SCHEMA },
    )))
    return { votes, lenses }
  },
  async (res, f) => {
    const votes = (res && res.votes) || []
    const lenses = (res && res.lenses) || []
    const live = votes.filter(Boolean)
    const confirms = live.filter(v => String(v.verdict).startsWith('confirmed'))
    const refutes = live.filter(v => String(v.verdict).startsWith('refuted'))
    const abstain = votes.length - live.length
    const survive = confirms.length >= NEED
    const status = survive ? 'confirmed' : (confirms.length + abstain >= NEED ? 'inconclusive' : 'rejected')
    const sevVotes = confirms.map(v => SEV[v.severity] || SEV[f.severity]).sort((a, b) => a - b)
    const finalSev = sevVotes.length ? SEV_NAMES[sevVotes[Math.floor(sevVotes.length / 2)] - 1] : f.severity
    const reproduced = confirms.filter(v => v.verdict === 'confirmed:reproduced').length
    const meanConf = confirms.length ? confirms.reduce((t, v) => t + (Number(v.confidence) || 0.5), 0) / confirms.length : 0
    return Object.assign({}, f, {
      status,
      final_severity: finalSev,
      tally: { confirmed: confirms.length, refuted: refutes.length, abstained: abstain, needed: NEED },
      verdicts: votes.map((v, j) => v ? { lens: lenses[j], verdict: v.verdict, severity: v.severity, evidence: String(v.evidence || '').slice(0, 600), true_cause: v.true_cause || undefined, settling_check: v.settling_check || undefined } : { lens: lenses[j], verdict: 'failed' }),
      score: SEV[finalSev] * 100 + reproduced * 10 + Math.round(meanConf * 9) + Math.min(f.reported_by - 1, 3),
    })
  },
)

const verified = decided.filter(Boolean)
const lostInVerify = toVerify.length - verified.length
if (lostInVerify > 0) note(`verify: ${lostInVerify} finding(s) lost to pipeline failures; listed as unverified`)
toVerify.forEach((f, i) => { if (!decided[i]) unverified.push(Object.assign({}, f, { reason: 'verification pipeline failed' })) })
const byRank = (a, b) => (b.score - a.score) || (a.file < b.file ? -1 : a.file > b.file ? 1 : 0) || (a.line - b.line)
const confirmed = verified.filter(f => f.status === 'confirmed').sort(byRank).map((f, i) => Object.assign({ rank: i + 1 }, f))
const inconclusive = verified.filter(f => f.status === 'inconclusive').sort(byRank)
const rejected = verified.filter(f => f.status === 'rejected').sort(byRank)
const leads = []
for (const f of verified) for (const v of f.verdicts) if (v.verdict === 'refuted:misattributed' && v.true_cause) leads.push({ from: f.id, lens: v.lens, true_cause: v.true_cause })
if (leads.length) note(`verify: ${leads.length} misattribution lead(s) reported as new, unverified claims`)
log(`verify: ${confirmed.length} confirmed, ${inconclusive.length} inconclusive, ${rejected.length} rejected of ${toVerify.length}`)

const stats = {
  files: files.length,
  shards: shards.length,
  finders: finderItems.length,
  failed_finders: failedFinders,
  raw: raw.length,
  unique: merged.length,
  verified: verified.length,
  confirmed: confirmed.length,
  inconclusive: inconclusive.length,
  rejected: rejected.length,
  unverified: unverified.length,
  below_floor: unverified.filter(f => f.below_floor).length,
  files_over_cap: filesCut,
  votes_per_finding: VOTES,
  by_severity: SEV_NAMES.slice().reverse().reduce((o, s) => { o[s] = confirmed.filter(f => f.final_severity === s).length; return o }, {}),
}

// ---------------- Report ----------------
phase('Report')
let reportPath = null
if (OUT_FILE) {
  // keep the payload valid JSON under 120k chars: drop verdict evidence from rejected first, then everywhere
  const slim = ev => f => ({ id: f.id, rank: f.rank, severity: f.final_severity || f.severity, file: f.file, line: f.line, title: f.title, failure_scenario: f.failure_scenario, fix: f.fix, dims: f.dims, tally: f.tally, verdicts: f.verdicts && (ev ? f.verdicts : f.verdicts.map(v => ({ lens: v.lens, verdict: v.verdict }))), reason: f.reason })
  const build = (evKept, evRejected) => JSON.stringify({ target: TARGET, scope: scopeInfo, stats, confirmed: confirmed.map(slim(evKept)), inconclusive: inconclusive.map(slim(evKept)), rejected: rejected.map(slim(evRejected)), unverified: unverified.map(slim(false)), leads, notes })
  let payload = build(true, true)
  if (payload.length > 120000) { payload = build(true, false); note('report: payload over 120000 chars; verdict evidence dropped for rejected findings') }
  if (payload.length > 120000) { payload = build(false, false); note('report: payload still over 120000 chars; verdict evidence dropped for all findings (see the returned object)') }
  if (payload.length > 120000) note(`report: payload ${payload.length} chars truncated to 120000; trailing sections (unverified, leads, notes) may be missing from the report`)
  const rep = await call(
    `Write a code-review report for the review-verify workflow (phase Report) to ${OUT_FILE} (mkdir -p the directory). Use only the data below; add nothing. Do not spawn subagents.
Layout:
1. Header: target, scope (kind, range, base/head, files reviewed, shards), dimensions, verification rule (${VOTES} lens(es), survive with >= ${NEED} confirming; failed lenses make a finding inconclusive).
2. Summary table: severity | confirmed count; then one line on coverage gaps (failed finders, files over the cap, unverified findings).
3. Confirmed findings ranked: "### #<rank> [<severity>] <file>:<line> <title>", then failure scenario, fix, dimensions, and a verdict table (lens | verdict | evidence excerpt).
4. Inconclusive findings (verifiers abstained or failed): same format, shorter.
5. Rejected findings: one line each with the refuting verdict and its evidence excerpt.
6. Unverified findings with the reason. 7. Misattribution leads. 8. Workflow notes.
Return the path and a summary of at most 6 lines.
DATA: ${payload.slice(0, 120000)}`,
    { label: 'report', phase: 'Report', agentType: 'file-summarizer', schema: { type: 'object', properties: { path: { type: 'string' }, summary: { type: 'string' } }, required: ['path', 'summary'] } },
  )
  if (rep) reportPath = rep.path || OUT_FILE
  else note(`report: writing ${OUT_FILE} failed; results are in the returned object only`)
}

return {
  started: true,
  completed: true,
  // coverage: every finder ran, no file cut, every eligible finding verified (below-floor nits are by design; see stats.below_floor)
  coverage_complete: failedFinders.length === 0 && filesCut === 0 && unverified.every(f => f.below_floor),
  target: TARGET,
  scope: Object.assign({}, scopeInfo, { files: files.length, shards: shards.length }),
  dimensions: dims,
  // with a report on disk, return digests only; scenarios, fixes and verdict evidence are in report_path
  confirmed: reportPath ? confirmed.map(f => ({ rank: f.rank, id: f.id, severity: f.final_severity, file: f.file, line: f.line, title: f.title, tally: f.tally })) : confirmed,
  inconclusive: reportPath ? inconclusive.map(f => ({ id: f.id, file: f.file, line: f.line, title: f.title, tally: f.tally })) : inconclusive,
  rejected: reportPath ? rejected.map(f => ({ id: f.id, file: f.file, line: f.line, title: f.title })) : rejected.map(f => ({ id: f.id, file: f.file, line: f.line, title: f.title, severity: f.severity, dims: f.dims, tally: f.tally, verdicts: f.verdicts })),
  unverified: unverified.map(f => ({ id: f.id, file: f.file, line: f.line, title: f.title, severity: f.severity, dims: f.dims, reason: f.reason })),
  leads,
  stats,
  report_path: reportPath,
  notes,
}
