export const meta = {
  name: 'plan-tournament',
  description: 'Planning tournament: one planner per strategic angle (architect for system-level goals) writes a complete candidate plan; blind judges score every candidate on feasibility, risk, cost, verifiability and completeness; medians, weights and Borda are computed in code; planner merges the winner with grafts; plan-critic red-teams; one revision.',
  whenToUse: 'Two or more credible plan shapes exist and a wrong pick is expensive: new systems, migrations, re-platforming, launches with hard constraints. args {goal, angles?: ["mvp-first","risk-first","performance-first","user-first"] (2-6; also cost-first, security-first, incremental-migration, simplicity-first, or any custom phrase), judges?: 3 (1-7), context?: string, systemLevel?: boolean (default: inferred from the goal), weights?: {feasibility, risk, cost, verifiability, completeness}, runTag?}. For a single obvious plan use the planner agent directly.',
  phases: [
    { title: 'Generate', detail: 'one planner (or architect for system-level goals) per angle writes a full candidate plan in planning-dag form, without naming its angle' },
    { title: 'Judge', detail: 'diverse judges (plan-critic, quality-control, architect, validator, planner; security-auditor and fact-checker for judges 6-7) score every candidate blind, in a per-judge rotated order, against an anchored 1-10 rubric' },
    { title: 'Synthesize', detail: 'medians per criterion, weighted totals, Borda tie-break and judge spread computed in code; planner merges the winner with the best runner-up ideas' },
    { title: 'Critique', detail: 'plan-critic red-teams the merged plan: premortem, hidden dependencies, unverifiable criteria, estimate optimism' },
    { title: 'Revise', detail: 'planner applies fixes for every blocker and major issue once and records a revision log' },
  ],
}

// ---------------------------------------------------------------------------
// Generate (barrier: judges compare all candidates) -> Judge (parallel, blind)
// -> aggregate in code -> Synthesize -> Critique -> one Revise.
// ---------------------------------------------------------------------------

const notes = []
function note(msg) { notes.push(msg); log(msg) }

function parseArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try { a = JSON.parse(a) } catch (e) { a = { goal: a } }
    if (typeof a === 'string') a = { goal: a }
  }
  return a && typeof a === 'object' && !Array.isArray(a) ? a : {}
}
const A = parseArgs(args)
const GOAL = typeof A.goal === 'string' ? A.goal.trim() : ''
if (!GOAL) {
  return {
    started: false,
    reason: 'args.goal (non-empty string) is required',
    next: 'Run Workflow plan-tournament with args {goal: "Move billing from the monolith to its own service with zero downtime by Q3", angles: ["mvp-first","risk-first","incremental-migration"], judges: 3, context: "team of 4, Postgres 16, Kafka available"}',
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
  if (t.length <= n) return t || 'plan'
  const cut = t.slice(0, n)
  const at = cut.lastIndexOf('-')
  return (at >= n / 2 ? cut.slice(0, at) : cut).replace(/-+$/g, '') || 'plan'
}
function tokens(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9.%]+/g, ' ').split(' ').map(w => w.replace(/^\.+|\.+$/g, '')).filter(w => w.length > 2 || /\d/.test(w))
}
function jaccard(a, b) {
  const x = new Set(tokens(a)), y = new Set(tokens(b))
  if (!x.size && !y.size) return 1
  let inter = 0
  for (const w of x) if (y.has(w)) inter++
  return inter / (x.size + y.size - inter)
}
function median(xs) {
  const s = xs.filter(Number.isFinite).slice().sort((a, b) => a - b)
  if (!s.length) return null
  const h = (s.length - 1) / 2
  return (s[Math.floor(h)] + s[Math.ceil(h)]) / 2
}
function mean(xs) { const s = xs.filter(Number.isFinite); return s.length ? s.reduce((t, x) => t + x, 0) / s.length : null }
function round(x, d) { return x === null || !Number.isFinite(x) ? x : Math.round(x * Math.pow(10, d)) / Math.pow(10, d) }
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

// ---------------- configuration ----------------
const ANGLE_TEXT = {
  'mvp-first': 'Deliver the smallest end-to-end slice that proves the core value first; defer generality and polish; every later milestone extends a system that already works in production.',
  'risk-first': 'Retire the riskiest assumptions first (the ones that would kill or reshape the project) with spikes and prototypes; sequence the rest after the unknowns are known; a rollback for every irreversible step.',
  'performance-first': 'Design around the hard performance and scale budgets (latency percentiles, throughput, memory, cost per request) from day one; benchmarks and load tests are gating milestones, not follow-ups.',
  'user-first': 'Start from the users\' workflows and acceptance; ship what users touch earliest, validate with real usage and telemetry, and let that feedback order the backlog.',
  'cost-first': 'Minimise total cost of ownership (engineering time, infrastructure, licences, on-call burden); reuse and buy before build; justify every new component.',
  'security-first': 'Threat-model first; least privilege, secrets handling, auditability and abuse cases are gating milestones; nothing ships without its controls.',
  'incremental-migration': 'Strangler-fig: keep the old system serving, migrate in reversible slices behind flags with dual-run and output comparison, cut over slice by slice.',
  'simplicity-first': 'The fewest moving parts and dependencies that meet the goal; boring, well-understood technology; delete before adding.',
}
let angles = Array.isArray(A.angles) && A.angles.length ? A.angles : ['mvp-first', 'risk-first', 'performance-first', 'user-first']
function angleKey(a) { return String(a).trim().toLowerCase().replace(/[\s_]+/g, '-') }
{
  const seenAngles = new Set()
  angles = angles.map(a => String(a).trim()).filter(a => {
    if (!a) return false
    if (seenAngles.has(angleKey(a))) { note(`angle "${a}" duplicates an earlier angle (case/spacing-insensitive); dropped`); return false }
    seenAngles.add(angleKey(a))
    return true
  })
}
if (angles.length > 6) { note(`angles capped at 6; dropped ${angles.slice(6).join(', ')}`); angles = angles.slice(0, 6) }
if (angles.length < 2) {
  return { started: false, reason: 'a tournament needs at least 2 distinct angles', next: 'Pass angles with 2-6 entries, or use the planner agent directly for a single plan.', notes }
}
for (const a of angles) if (!ANGLE_TEXT[angleKey(a)]) note(`angle "${a}" is custom; candidates get the brief "optimise primarily for: ${a}"`)
function angleText(a) { return ANGLE_TEXT[angleKey(a)] || `Optimise primarily for: ${a}. Make that priority explicit in the sequencing and trade-offs.` }

const JUDGES = clampInt(A.judges, 1, 7, 3)
if (A.judges !== undefined && JUDGES !== Number(A.judges)) note(`judges clamped to ${JUDGES} (allowed 1-7)`)
if (JUDGES < 3) note(`only ${JUDGES} judge(s): medians degrade to single opinions; use 3+ for a robust ranking`)
const CRITERIA = ['feasibility', 'risk', 'cost', 'verifiability', 'completeness']
const DEFAULT_WEIGHTS = { feasibility: 0.25, risk: 0.2, cost: 0.15, verifiability: 0.2, completeness: 0.2 }
let weights = Object.assign({}, DEFAULT_WEIGHTS)
if (A.weights && typeof A.weights === 'object') {
  const w = {}
  let ok = true
  for (const c of CRITERIA) {
    const v = A.weights[c] === undefined ? DEFAULT_WEIGHTS[c] : Number(A.weights[c])
    if (!Number.isFinite(v) || v < 0) ok = false
    w[c] = v
  }
  const sum = CRITERIA.reduce((t, c) => t + w[c], 0)
  if (ok && sum > 0) { for (const c of CRITERIA) w[c] = round(w[c] / sum, 4); weights = w }
  else note('weights invalid (need non-negative numbers with a positive sum); using defaults')
}
const SYSTEM_RE = /\b(architecture|architect|system design|distributed|micro-?services?|(own|separate|new|standalone) services?|platform|infrastructure|data model|storage engine|scal(e|ing|ability)|multi-region|event[- ]driven|database|message queue|replication|re-?platform)/i
const SYSTEM_LEVEL = typeof A.systemLevel === 'boolean' ? A.systemLevel : SYSTEM_RE.test(GOAL + ' ' + (A.context || ''))
const GENERATOR = SYSTEM_LEVEL ? 'architect' : 'planner'
log(`${angles.length} angle(s): ${angles.join(', ')}; generator ${GENERATOR}${typeof A.systemLevel === 'boolean' ? '' : ' (system-level ' + (SYSTEM_LEVEL ? 'inferred from the goal' : 'not inferred') + '; pass systemLevel to override)'}; ${JUDGES} judge(s)`)

const SLUG = slugify(GOAL, 48)
const TAG = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + slugify(A.runTag, 24) : ''
const RUN_DIR = `.stack/out/plan-tournament/${SLUG}${TAG}`
if (!TAG) note(`output directory ${RUN_DIR} (pass runTag to keep separate runs of the same goal apart)`)
const CONTEXT = typeof A.context === 'string' ? A.context.trim().slice(0, 6000) : (Array.isArray(A.context) ? 'Read these first: ' + A.context.join(', ') : '')
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
const candidates = angles.map((a, i) => ({ letter: LETTERS[i], angle: a, path: `${RUN_DIR}/candidates/${LETTERS[i]}.md` }))

// ---------------- Generate ----------------
phase('Generate')
const CANDIDATE_SCHEMA = {
  type: 'object',
  properties: {
    plan_path: { type: 'string' },
    summary: { type: 'string', description: '<= 12 lines; must not name the strategy or the author' },
    task_count: { type: 'integer' },
    critical_path: { type: 'array', items: { type: 'string' } },
    milestones: { type: 'array', items: { type: 'string' } },
    top_risks: { type: 'array', items: { type: 'string' } },
    cost_estimate: { type: 'string', description: 'effort (person-days or agent turns) plus infrastructure and external costs' },
    key_ideas: { type: 'array', items: { type: 'string' }, description: '3-6 distinctive ideas another plan could adopt' },
    assumptions: { type: 'array', items: { type: 'string' } },
  },
  required: ['plan_path', 'summary', 'critical_path', 'top_risks', 'cost_estimate', 'key_ideas'],
}
const gen = await parallel(candidates.map(c => () => call(
  `You are writing candidate plan ${c.letter} for the plan-tournament workflow (phase Generate). Blind judges will score it against other candidates: do not name your strategy, your agent name, or the tournament anywhere in the file or the summary; the plan must stand on its own. You are inside plan-tournament: do not run plan-tournament or any other saved workflow and do not spawn planners or architects; at most 3 leaf lookups (quick-researcher, Explore) for facts that change the plan's shape.

GOAL: ${GOAL}
${CONTEXT ? 'CONTEXT AND CONSTRAINTS: ' + CONTEXT + '\n' : ''}STRATEGY TO OPTIMISE FOR (hidden from judges): ${angleText(c.angle)}
Stay credible on every criterion the judges use: feasibility, risk, cost, verifiability, completeness. A strategy is a priority order, not an excuse to drop part of the goal.

Write ${c.path} (mkdir -p first) in planning-dag form, with these sections:
- Goal restatement and measurable success criteria.
${SYSTEM_LEVEL ? '- Architecture decision: components, data flow, interfaces and the key trade-off, ADR-style (context, decision, consequences, rejected alternatives).\n' : ''}- Assumptions, each with the spike or check that would falsify it.
- Task DAG table: id | task | owner (an agent of this stack or a human role) | depends on | acceptance criterion (checkable: command, test, metric, document) | estimate.
- Parallel groups and the critical path.
- Milestones with exit criteria.
- Risks: risk | likelihood | impact | mitigation | re-plan trigger.
- Cost: effort, infrastructure and external costs, with the basis of the estimate.
- Rollout and rollback for every irreversible step; observability and the signals that prove success.
Return the schema; key_ideas are the 3-6 ideas in this plan another plan could adopt.`,
  { label: `gen:${c.letter}`, phase: 'Generate', agentType: GENERATOR, schema: CANDIDATE_SCHEMA },
)))
const live = []
gen.forEach((g, i) => {
  if (!g) { note(`candidate ${candidates[i].letter} (${candidates[i].angle}) failed to generate; excluded`); return }
  live.push(Object.assign({}, candidates[i], { gen: g, path: g.plan_path || candidates[i].path }))
})
if (!live.length) return { started: true, completed: false, reason: 'no candidate plan was generated', notes }
if (live.length < 2) {
  note(`only candidate ${live[0].letter} (${live[0].angle}) was generated; a one-plan tournament is skipped (no judging, synthesis or critique)`)
  return {
    started: true, completed: false, reason: 'only one candidate generated; nothing to rank',
    candidate: { letter: live[0].letter, angle: live[0].angle, path: live[0].path, summary: live[0].gen.summary },
    next: 'Use the candidate as a draft and red-team it with plan-critic, or re-run with more angles.', run_dir: RUN_DIR, notes,
  }
}

// Strip strategy names from anything the judges read inline.
function sanitize(t) {
  let s = String(t || '')
  for (const a of angles) {
    const pat = a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/[-\s]+/g, '[-\\s]?')
    s = s.replace(new RegExp(pat, 'gi'), '[strategy]')
  }
  return s.replace(/\b(MVP|minimum viable product)\b/g, 'first release').replace(/\btournament\b/gi, 'review')
}

// ---------------- Judge ----------------
phase('Judge')
const JUDGE_POOL = [
  { agentType: 'plan-critic', persona: 'red-team lead: hunts hidden dependencies, optimistic estimates, unverifiable criteria and late-discovered risk' },
  { agentType: 'quality-control', persona: 'delivery assurance: traces every requirement of the goal to tasks and to evidence that it was met' },
  { agentType: 'architect', persona: 'principal engineer: technical soundness, operability, failure modes and long-term cost' },
  { agentType: 'validator', persona: 'verification engineer: can every acceptance criterion pass or fail mechanically?' },
  { agentType: 'planner', persona: 'programme manager: sequencing, staffing, critical-path realism and estimate basis' },
  // judges 6-7: further agent types (tiers are authoritative; no per-call model/effort)
  { agentType: 'security-auditor', persona: 'security and compliance reviewer: threat model, data handling, access control and audit gates as milestones' },
  { agentType: 'fact-checker', persona: 'premise checker: tool capabilities, versions, limits and cost figures the plan relies on are true as stated' },
]
const judges = Array.from({ length: JUDGES }, (_, j) => Object.assign({ label: 'J' + (j + 1) }, JUDGE_POOL[j]))
function orderFor(j) {
  const n = live.length
  const rot = live.map((_, i) => live[(i + j) % n])
  return j % 2 === 1 ? rot.reverse() : rot
}
const SCORE = { type: 'number', minimum: 1, maximum: 10 }
const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    scores: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          candidate: { type: 'string', description: 'the candidate letter' },
          feasibility: SCORE, risk: SCORE, cost: SCORE, verifiability: SCORE, completeness: SCORE,
          rationale: { type: 'string', description: '<= 3 lines' },
          best_ideas: { type: 'array', items: { type: 'string' }, description: 'ideas from THIS candidate worth grafting into the winner' },
          fatal_flaw: { type: 'string', description: 'a flaw that makes the plan fail as written; empty if none' },
        },
        required: ['candidate', 'feasibility', 'risk', 'cost', 'verifiability', 'completeness', 'rationale'],
      },
    },
    ranking: { type: 'array', items: { type: 'string' }, description: 'all candidate letters, best first' },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['scores', 'ranking'],
}
const RUBRIC = `Rubric: score every candidate 1-10 on each criterion, using the anchors.
- feasibility: 1 = depends on unproven technology, missing access or impossible staffing; 5 = feasible with notable unknowns that have spikes; 10 = every task executable by a named owner with known tools.
- risk (higher = better risk posture): 1 = top risks unmitigated or discovered late; 5 = main risks identified with mitigations, some retired late; 10 = riskiest assumptions retired first, rollback for every irreversible step.
- cost (higher = cheaper for the same outcome): 1 = gold-plated, more than 2x a reasonable baseline; 5 = reasonable; 10 = minimal cost for the full goal, no wasted work.
- verifiability: 1 = acceptance criteria vague; 5 = most tasks have checkable criteria; 10 = every task has a command, test or metric that passes or fails.
- completeness: 1 = misses major parts of the goal; 5 = covers the goal but misses rollout, migration, observability or docs; 10 = the goal plus rollout, migration, observability and rollback.`
const judged = await parallel(judges.map((jd, j) => () => {
  const order = orderFor(j)
  return call(
    `You are judge ${jd.label} in a blind planning review (plan-tournament workflow, phase Judge). Perspective: ${jd.persona}. Score independently. Do not spawn subagents or run workflows. Read every candidate file in full before scoring; judge the plans as written and do not reward length.

GOAL: ${GOAL}
${CONTEXT ? 'CONTEXT AND CONSTRAINTS: ' + CONTEXT + '\n' : ''}
Candidates (labels are arbitrary; the order is shuffled per judge):
${order.map(c => `- Candidate ${c.letter}: ${c.path}\n  Author summary: ${sanitize(c.gen.summary).replace(/\s+/g, ' ').slice(0, 700)}`).join('\n')}

${RUBRIC}

Also return: ranking (all candidate letters, best first); per candidate best_ideas worth grafting into whichever plan wins, and fatal_flaw (empty if none).`,
    { label: `judge:${jd.label}`, phase: 'Judge', agentType: jd.agentType, schema: JUDGE_SCHEMA },
  )
}))

// ---------------- aggregate (code) ----------------
const letters = live.map(c => c.letter)
const per = {}
for (const c of live) per[c.letter] = { crit: {}, judgeTotals: [], borda: 0, fatal: [], ideas: [], rationales: [] }
for (const c of live) for (const k of CRITERIA) per[c.letter].crit[k] = []
let validJudges = 0
judged.forEach((jr, j) => {
  if (!jr) { note(`judge ${judges[j].label} (${judges[j].agentType}) failed; excluded from the tally`); return }
  validJudges++
  const seen = new Set()
  for (const s of (jr.scores || [])) {
    const L = String(s.candidate || '').trim().replace(/^candidate\s+/i, '').toUpperCase().slice(0, 1)
    if (!per[L] || seen.has(L)) continue
    seen.add(L)
    let total = 0
    for (const k of CRITERIA) {
      const v = Math.min(10, Math.max(1, Number(s[k])))
      if (Number.isFinite(v)) { per[L].crit[k].push(v); total += weights[k] * v }
    }
    per[L].judgeTotals.push(total)
    if (s.fatal_flaw && String(s.fatal_flaw).trim()) per[L].fatal.push({ judge: judges[j].label, flaw: String(s.fatal_flaw).trim() })
    for (const idea of (s.best_ideas || [])) per[L].ideas.push({ judge: judges[j].label, idea: String(idea).trim() })
    if (s.rationale) per[L].rationales.push(`${judges[j].label}: ${String(s.rationale).trim()}`)
  }
  const missing = letters.filter(L => !seen.has(L))
  if (missing.length) note(`judge ${judges[j].label} did not score candidate(s) ${missing.join(', ')}`)
  const rk = []
  for (const x of (jr.ranking || [])) {
    const L = String(x).trim().replace(/^candidate\s+/i, '').toUpperCase().slice(0, 1)
    if (per[L] && !rk.includes(L)) rk.push(L)
  }
  rk.forEach((L, pos) => { per[L].borda += (letters.length - 1 - pos) })
})
if (!validJudges) note('no judge returned scores; the winner falls back to candidate A unscored')

const table = live.map(c => {
  const p = per[c.letter]
  const med = {}
  for (const k of CRITERIA) med[k] = median(p.crit[k])
  const scored = CRITERIA.every(k => med[k] !== null)
  const weighted = scored ? CRITERIA.reduce((t, k) => t + weights[k] * med[k], 0) : null
  const spread = p.judgeTotals.length ? Math.max.apply(null, p.judgeTotals) - Math.min.apply(null, p.judgeTotals) : null
  return {
    letter: c.letter, angle: c.angle, path: c.path,
    medians: med, weighted: round(weighted, 3), mean_of_judge_totals: round(mean(p.judgeTotals), 3), judge_spread: round(spread, 3),
    borda: p.borda, judges_scored: p.judgeTotals.length, fatal_flaws: p.fatal, rationales: p.rationales,
  }
})
table.sort((a, b) =>
  ((b.weighted === null ? -1 : b.weighted) - (a.weighted === null ? -1 : a.weighted)) ||
  (b.borda - a.borda) || (a.fatal_flaws.length - b.fatal_flaws.length) ||
  ((a.judge_spread === null ? 99 : a.judge_spread) - (b.judge_spread === null ? 99 : b.judge_spread)) ||
  (a.letter < b.letter ? -1 : 1))
table.forEach((t, i) => { t.rank = i + 1 })
const winner = table[0]
if (winner.weighted === null) note(`no candidate received a complete score from any judge; winner ${winner.letter} chosen by Borda then label order, treat the ranking as unreliable`)
const runnerUp = table[1] || null
const margin = runnerUp && winner.weighted !== null && runnerUp.weighted !== null ? round(winner.weighted - runnerUp.weighted, 3) : null
const closeCall = margin !== null && margin < 0.5
const winnerFlagged = winner.fatal_flaws.length * 2 > validJudges && validJudges > 0
const highDisagreement = table.filter(t => t.judge_spread !== null && t.judge_spread > 2).map(t => t.letter)
if (closeCall) note(`close call: ${winner.letter} leads ${runnerUp.letter} by ${margin} weighted points (< 0.5); synthesis grafts the runner-up more aggressively`)
if (winnerFlagged) note(`a majority of judges named a fatal flaw in the winner ${winner.letter}; synthesis must fix it`)
if (highDisagreement.length) note(`judges disagree by > 2 weighted points on candidate(s) ${highDisagreement.join(', ')}`)
log(`ranking: ${table.map(t => `${t.letter}(${t.angle})=${t.weighted}`).join(' > ')}`)

// Graft pool: judge-nominated ideas from non-winners first, then generator key ideas of close runners-up.
const grafts = []
for (const t of table.slice(1)) {
  for (const x of per[t.letter].ideas) grafts.push({ from: t.letter, angle: t.angle, idea: x.idea, by: 'judge ' + x.judge })
}
for (const t of table.slice(1)) {
  if (winner.weighted !== null && t.weighted !== null && winner.weighted - t.weighted > 2) continue
  const g = live.find(c => c.letter === t.letter).gen
  for (const idea of (g.key_ideas || [])) grafts.push({ from: t.letter, angle: t.angle, idea: String(idea).trim(), by: 'author' })
}
const graftPool = []
for (const g of grafts) if (g.idea && !graftPool.some(x => jaccard(x.idea, g.idea) >= 0.6)) graftPool.push(g)
const graftCap = closeCall ? 16 : 12
if (graftPool.length > graftCap) note(`graft pool capped at ${graftCap}; ${graftPool.length - graftCap} lower-priority idea(s) not offered to synthesis`)
const offered = graftPool.slice(0, graftCap)
const winnerWeakest = CRITERIA.slice().sort((a, b) => (winner.medians[a] || 0) - (winner.medians[b] || 0))[0]

// ---------------- Synthesize ----------------
phase('Synthesize')
const PLAN_PATH = `${RUN_DIR}/plan.md`
const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    plan_path: { type: 'string' },
    summary: { type: 'string', description: '<= 12 lines' },
    critical_path: { type: 'array', items: { type: 'string' } },
    task_count: { type: 'integer' },
    grafts_applied: { type: 'array', items: { type: 'string' } },
    grafts_rejected: { type: 'array', items: { type: 'object', properties: { idea: { type: 'string' }, reason: { type: 'string' } }, required: ['idea', 'reason'] } },
    flaws_fixed: { type: 'array', items: { type: 'string' } },
  },
  required: ['plan_path', 'summary', 'critical_path', 'grafts_applied'],
}
const scoreLines = table.map(t => `${t.rank}. ${t.letter} (${t.angle}) weighted ${t.weighted} | ${CRITERIA.map(k => k + ' ' + t.medians[k]).join(', ')} | Borda ${t.borda} | spread ${t.judge_spread} | fatal flaws ${t.fatal_flaws.length}`).join('\n')
const synth = await call(
  `You are the planner merging the result of a planning tournament (plan-tournament workflow, phase Synthesize). Do not run workflows and do not spawn planners or architects; at most 3 leaf lookups.

GOAL: ${GOAL}
${CONTEXT ? 'CONTEXT AND CONSTRAINTS: ' + CONTEXT + '\n' : ''}
WINNER (base plan): candidate ${winner.letter}, strategy "${winner.angle}", file ${winner.path}
Scores (medians of ${validJudges} blind judge(s), weights ${JSON.stringify(weights)}):
${scoreLines}
Margin over the runner-up: ${margin === null ? 'n/a' : margin}${closeCall ? ' (close call: weigh the runner-up\'s structure seriously)' : ''}
Winner's weakest criterion: ${winnerWeakest} (${winner.medians[winnerWeakest]})
Fatal flaws judges named in the winner: ${winner.fatal_flaws.length ? winner.fatal_flaws.map(f => f.judge + ': ' + f.flaw).join(' | ') : 'none'}
Judge rationales for the winner: ${winner.rationales.join(' | ').slice(0, 1500)}
Runner-up files for reference: ${table.slice(1).map(t => t.letter + ' ' + t.path).join(', ') || 'none'}

GRAFT CANDIDATES:
${offered.map((g, i) => `${i + 1}. [from ${g.from} / ${g.angle}, nominated by ${g.by}] ${g.idea}`).join('\n') || 'none'}

Write ${PLAN_PATH} (mkdir -p): start from the winner's file; graft an idea only when it improves a rubric criterion (especially ${winnerWeakest}) without breaking the winner's critical path or adding cost beyond its benefit; fix every fatal flaw named above. Keep the planning-dag sections (success criteria, assumptions with falsifying checks, task DAG with owners and checkable acceptance criteria, parallel groups, critical path, milestones, risks, cost, rollout/rollback, observability). Add a "Grafts" section: idea | from | applied or rejected | why. Also write ${RUN_DIR}/plan.json with {"tasks": [{"id","title","owner","depends_on","acceptance","estimate"}]} for machine use. Also write ${RUN_DIR}/scores.md: the score table above plus, per candidate, these judge rationales and fatal flaws: ${JSON.stringify(table.map(t => ({ letter: t.letter, rationales: t.rationales, fatal_flaws: t.fatal_flaws }))).slice(0, 12000)}`,
  { label: 'synthesize', phase: 'Synthesize', agentType: 'planner', schema: SYNTH_SCHEMA },
)
if (!synth) note(`synthesis failed; the winner's file ${winner.path} is returned unmerged`)
let planPath = synth ? (synth.plan_path || PLAN_PATH) : winner.path

// ---------------- Critique ----------------
phase('Critique')
const CRITIQUE_SCHEMA = {
  type: 'object',
  properties: {
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          issue: { type: 'string' },
          location: { type: 'string', description: 'section or task id' },
          fix: { type: 'string' },
        },
        required: ['id', 'severity', 'issue', 'fix'],
      },
    },
    verdict: { type: 'string', enum: ['ship', 'revise', 'rethink'] },
    summary: { type: 'string' },
  },
  required: ['issues', 'verdict'],
}
const critique = await call(
  `Red-team the plan at ${planPath} (plan-tournament workflow, phase Critique). This IS the tournament: do not recommend or run plan-tournament or any other saved workflow; at most 3 leaf lookups to check a fact the plan relies on.

GOAL: ${GOAL}
${CONTEXT ? 'CONTEXT AND CONSTRAINTS: ' + CONTEXT + '\n' : ''}
Check: missing steps and hidden dependencies; unverifiable acceptance criteria; a premortem (it is six months later and this plan failed: the three most likely reasons); single points of failure (people, systems, vendors); risks discovered too late in the sequence; estimate optimism against reference classes; owners who cannot do the task; irreversible steps without rollback; over-engineering for the goal.
Each issue: id (K1, K2, ...), severity (blocker: fails as written; major: likely significant overrun or rework; minor: improvement), location (section or task id), and a concrete fix. verdict: ship (no blocker or major), revise, or rethink (the plan shape itself is wrong).`,
  { label: 'critique', phase: 'Critique', agentType: 'plan-critic', schema: CRITIQUE_SCHEMA },
)
if (!critique) note('critique failed; the plan is returned unreviewed')
const issues = critique ? (critique.issues || []) : []
const serious = issues.filter(i => i.severity === 'blocker' || i.severity === 'major')

// ---------------- Revise (once) ----------------
phase('Revise')
let revision = null
let version = synth ? 'merged' : 'winner-unmerged'
if (critique && (serious.length || critique.verdict !== 'ship')) {
  if (!synth) {
    note('revise: skipped because synthesis failed; apply the critique to the winner file manually or re-run')
  } else {
    const REVISE_SCHEMA = {
      type: 'object',
      properties: {
        plan_path: { type: 'string' },
        summary: { type: 'string' },
        addressed: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, change: { type: 'string' } }, required: ['id', 'change'] } },
        declined: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, reason: { type: 'string' } }, required: ['id', 'reason'] } },
        critical_path: { type: 'array', items: { type: 'string' } },
      },
      required: ['plan_path', 'summary', 'addressed', 'declined'],
    }
    revision = await call(
      `Revise the merged plan once (plan-tournament workflow, phase Revise). Do not run workflows or spawn planners.
1. Copy ${planPath} to ${RUN_DIR}/plan-v1.md (keep it unchanged).
2. Edit ${planPath} in place: apply a fix for EVERY blocker and major issue below; apply minor ones when cheap. A fix you decline needs a reason grounded in the goal or constraints.
3. Append a "Revision log" section: issue id | change made, or declined with reason. Update ${RUN_DIR}/plan.json to match.
GOAL: ${GOAL}
Critic verdict: ${critique.verdict}${critique.summary ? ' - ' + critique.summary : ''}
ISSUES:
${issues.map(i => `${i.id} [${i.severity}] ${i.location ? '(' + i.location + ') ' : ''}${i.issue} -> fix: ${i.fix}`).join('\n')}`,
      { label: 'revise', phase: 'Revise', agentType: 'planner', schema: REVISE_SCHEMA },
    )
    if (revision) { version = 'revised'; planPath = revision.plan_path || planPath }
    else note('revise: revision failed; the merged plan is returned with the open critique')
    if (revision) {
      const declinedSerious = (revision.declined || []).filter(d => serious.some(s => s.id === d.id))
      if (declinedSerious.length) note(`revise: ${declinedSerious.length} blocker/major issue(s) declined by the planner: ${declinedSerious.map(d => d.id).join(', ')}`)
    }
  }
} else if (critique) {
  log('critique: verdict ship with no blocker or major issue; no revision needed')
}
const needsRethink = !!(critique && critique.verdict === 'rethink')
if (needsRethink) note('critic verdict "rethink": the plan shape may be wrong; consider re-running with different angles or an architect spike')

return {
  started: true,
  completed: !!synth,
  plan_path: planPath,
  plan: {
    version,
    summary: revision ? revision.summary : (synth ? synth.summary : live.find(c => c.letter === winner.letter).gen.summary),
    critical_path: (revision && revision.critical_path) || (synth ? synth.critical_path : live.find(c => c.letter === winner.letter).gen.critical_path),
    task_count: synth ? synth.task_count : undefined,
    grafts_applied: synth ? synth.grafts_applied : [],
    grafts_rejected: synth ? (synth.grafts_rejected || []) : [],
    flaws_fixed: synth ? (synth.flaws_fixed || []) : [],
    json_path: synth ? `${RUN_DIR}/plan.json` : null,
    previous_version_path: revision ? `${RUN_DIR}/plan-v1.md` : null,
  },
  winner: { letter: winner.letter, angle: winner.angle, path: winner.path, flagged_fatal_flaw: winnerFlagged },
  ranking: table.map(t => ({ rank: t.rank, letter: t.letter, angle: t.angle, weighted: t.weighted })),
  scores: synth ? table.map(t => ({ rank: t.rank, letter: t.letter, weighted: t.weighted, medians: t.medians, borda: t.borda, judge_spread: t.judge_spread, fatal_flaws: t.fatal_flaws.length })) : table,
  scores_path: synth ? `${RUN_DIR}/scores.md` : null,
  margin,
  close_call: closeCall,
  weights,
  judges: judges.map((jd, j) => ({ label: jd.label, agentType: jd.agentType, returned: !!judged[j] })),
  critique: critique ? {
    verdict: critique.verdict,
    summary: critique.summary || '',
    issues,
    addressed: revision ? revision.addressed : [],
    declined: revision ? revision.declined : [],
  } : null,
  needs_rethink: needsRethink,
  generator: GENERATOR,
  run_dir: RUN_DIR,
  notes,
}
