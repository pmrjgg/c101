export const meta = {
  name: 'fanout',
  description: 'Generic concurrent map: one agent of a given type per item, prompt rendered from a template, optional JSON schema for structured results, retry on null or empty, ordered results plus a failure list',
  whenToUse: 'Many independent, homogeneous items that each need the same agent and the same instructions and no cross-item merge (classify 80 issues, summarise 40 papers, port 30 small files, check 50 URLs). Use the swarm-run workflow instead when results need dedup, coverage accounting or retries of partial work. Main thread only. args {items: [any], agentType, promptTemplate with {{item}} {{index}} {{n}} {{total}} {{item.field}}, schema?, model? (opus|sonnet|haiku, general-purpose only), effort? (general-purpose only), retry?=1, maxItems?=400, outDir?, runTag?}',
  phases: [
    { title: 'Map', detail: 'first attempt for every item, pipelined; the runtime runs about 10-16 agents at a time' },
    { title: 'Retry', detail: 'items whose agent returned null, empty text or threw are re-run, up to retry times (default 1)' },
  ],
}

// ---------------------------------------------------------------------------- constants
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
const DEFAULT_MAX_ITEMS = 400   // (1 + retry) agents per item; the runtime caps a workflow at 1000 agents
const HARD_MAX_ITEMS = 900
const AGENT_CAP = 990           // workflow agent cap (1000) minus a small reserve; maxItems * (1 + retry) must fit
const MODELS = ['opus', 'sonnet', 'haiku']   // tier aliases; only general-purpose takes a per-call model
const RESULT_CAP = 3000         // chars of one free-text result carried in the return value (context policy)
const MAX_RETRY = 3
const RETRY_MIN_BUDGET = 20000  // tokens; below this (with a budget set) retries are skipped
const TOKEN_RE = /\{\{\s*(item(?:\.[A-Za-z0-9_$-]+)*|index|n|total)\s*\}\}/g

// ---------------------------------------------------------------------------- helpers
function isBlank(v) { return v === null || v === undefined || (typeof v === 'string' && !v.trim()) }
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) : s }
function slugify(s, n) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, n) || 'run' }
function show(v) { return v === undefined || v === null ? '' : (typeof v === 'string' ? v : JSON.stringify(v, null, 2)) }
function getPath(obj, path) {
  let cur = obj
  for (const p of path) {
    if (cur === null || cur === undefined || typeof cur !== 'object') return undefined
    cur = cur[p]
  }
  return cur
}
function ref(item, i) {
  if (typeof item === 'string') return clip(item.replace(/\s+/g, ' ').trim(), 40)
  if (item && typeof item === 'object') {
    for (const k of ['id', 'name', 'path', 'file', 'url', 'title', 'key']) if (typeof item[k] === 'string' || typeof item[k] === 'number') return clip(String(item[k]), 40)
    return clip(JSON.stringify(item), 40)
  }
  return item === undefined ? '#' + i : clip(String(item), 40)
}
function parseMaybeJson(v) {
  if (typeof v !== 'string') return { ok: true, value: v }
  try { return { ok: true, value: JSON.parse(v) } } catch (e) { return { ok: false, error: e.message } }
}
function schemaError(s) {
  if (!s || typeof s !== 'object' || Array.isArray(s)) return 'schema must be a JSON Schema object'
  if (s.type !== 'object') return 'schema root must have type "object" (wrap arrays as {type:"object", properties:{items:{type:"array", ...}}})'
  if (!s.properties || typeof s.properties !== 'object' || Array.isArray(s.properties) || !Object.keys(s.properties).length) return 'schema root needs a non-empty "properties" object'
  if (s.required !== undefined) {
    if (!Array.isArray(s.required)) return 'schema "required" must be an array'
    const extra = s.required.filter(k => !(k in s.properties))
    if (extra.length) return 'schema "required" names keys missing from properties: ' + extra.join(', ')
  }
  return null
}
async function call(prompt, opts) {
  try {
    const value = await agent(prompt, opts)
    return { value, error: isBlank(value) ? (value == null ? 'agent returned null' : 'agent returned empty text') : null }
  } catch (e) {
    return { value: null, error: 'agent threw: ' + clip(e && e.message ? e.message : e, 300) }
  }
}

// ---------------------------------------------------------------------------- args
const USAGE = 'Main thread only: call the Workflow tool with name "fanout" and args {items: [...], agentType (a stack agent name), promptTemplate (containing {{item}}), schema?, model? and effort? (general-purpose only; model opus|sonnet|haiku), retry?, outDir?, runTag?}. Each rendered prompt must be a self-contained brief: goal, inputs as paths, constraints, acceptance criteria, output shape.'
const pa = args === undefined || args === null || args === '' ? { ok: true, value: {} } : parseMaybeJson(args)
if (!pa.ok) return { started: false, reason: 'args is a string but not valid JSON: ' + pa.error, next: USAGE }
const A = pa.value
if (!A || typeof A !== 'object' || Array.isArray(A)) return { started: false, reason: 'args must be a JSON object', next: USAGE }

const pi = parseMaybeJson(A.items)
const items = pi.ok && Array.isArray(pi.value) ? pi.value : null
const agentType = typeof A.agentType === 'string' ? A.agentType.trim() : ''
let template = typeof A.promptTemplate === 'string' ? A.promptTemplate : ''
const missing = []
if (!items || !items.length) missing.push('items (non-empty array)')
if (!agentType) missing.push('agentType (a stack agent name such as source-summarizer, web-scraper, reviewer, or general-purpose)')
if (!template.trim()) missing.push('promptTemplate (string containing {{item}})')
if (missing.length) return { started: false, reason: 'missing or invalid: ' + missing.join('; '), next: USAGE }

let schema
if (A.schema !== undefined && A.schema !== null && A.schema !== '') {
  const ps = parseMaybeJson(A.schema)
  if (!ps.ok) return { started: false, reason: 'schema is a string but not valid JSON: ' + ps.error, next: USAGE }
  const err = schemaError(ps.value)
  if (err) return { started: false, reason: err, next: USAGE }
  schema = ps.value
}
// Tiers are authoritative: stack agents run on their tier and learned effort; only general-purpose takes overrides.
const GP = agentType === 'general-purpose'
const rawModel = typeof A.model === 'string' ? A.model.trim().toLowerCase() : ''
const model = GP && MODELS.includes(rawModel) ? rawModel : undefined
if (!GP && (A.model || A.effort)) log('model/effort ignored: ' + agentType + ' runs on its tier and learned effort from config/models.json (overrides apply to general-purpose only)')
else if (rawModel && !model) log('model "' + A.model + '" ignored: general-purpose takes only ' + MODELS.join('|'))
let effort = GP && typeof A.effort === 'string' ? A.effort.trim().toLowerCase() : undefined
if (effort && !EFFORTS.includes(effort)) { log('effort "' + effort + '" is not one of ' + EFFORTS.join('/') + '; ignored, agents use their frontmatter default'); effort = undefined }
let retry = A.retry === undefined ? 1 : Math.max(0, Math.floor(Number(A.retry)) || 0)
if (retry > MAX_RETRY) { log('retry=' + retry + ' capped at ' + MAX_RETRY); retry = MAX_RETRY }
let maxItems = A.maxItems === undefined ? DEFAULT_MAX_ITEMS : Math.max(1, Math.floor(Number(A.maxItems)) || DEFAULT_MAX_ITEMS)
if (maxItems > HARD_MAX_ITEMS) { log('maxItems=' + maxItems + ' capped at ' + HARD_MAX_ITEMS + ' (workflow agent cap is 1000)'); maxItems = HARD_MAX_ITEMS }
const agentCapItems = Math.floor(AGENT_CAP / (1 + retry))
if (maxItems > agentCapItems) { log('maxItems=' + maxItems + ' capped at ' + agentCapItems + ' so (1 + retry=' + retry + ') attempts per item stay under the 1000-agent workflow cap'); maxItems = agentCapItems }
const runTag = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + slugify(A.runTag, 24) : ''
const outDir = (typeof A.outDir === 'string' && A.outDir.trim() ? A.outDir.trim() : '.stack/out/fanout/' + slugify(agentType + '-' + template, 40) + runTag).replace(/\/+$/, '')

const templateWarnings = []
if (!/\{\{\s*item(?:\.[A-Za-z0-9_$-]+)*\s*\}\}/.test(template)) {
  templateWarnings.push('promptTemplate has no {{item}} placeholder; the item was appended under "ITEM:"')
  template = template.replace(/\s+$/, '') + '\n\nITEM:\n{{item}}'
}

// ---------------------------------------------------------------------------- render (up front, so template bugs stop the run before any spend)
let work = items.map((item, index) => ({ item, index }))
let skipped = []
if (work.length > maxItems) {
  skipped = work.slice(maxItems).map(w => ({ index: w.index, ref: ref(w.item, w.index), reason: 'capped by maxItems=' + maxItems }))
  work = work.slice(0, maxItems)
  log('CAPPED: items ' + maxItems + '..' + (items.length - 1) + ' (' + skipped.length + ') were NOT run; pass them in a second Workflow name=fanout call')
}
const total = items.length
const missCount = {}
for (const w of work) {
  w.ref = ref(w.item, w.index)
  w.prompt = template.replace(TOKEN_RE, (m, name) => {
    if (name === 'index') return String(w.index)
    if (name === 'n') return String(w.index + 1)
    if (name === 'total') return String(total)
    if (name === 'item') return show(w.item)
    const v = getPath(w.item, name.split('.').slice(1))
    if (v === undefined) missCount[name] = (missCount[name] || 0) + 1
    return show(v)
  })
  w.out = outDir + '/' + String(w.index + 1).padStart(String(total).length, '0') + '.md'
  w.prompt += '\n\nOUTPUT (context policy): write your full deliverable to ' + w.out + ' (create directories as needed). ' +
    (schema ? 'Keep each structured field short; put long text in that file and reference its path.' : 'Return at most ~40 lines / 3k characters: the output-contract sections with a short Result, plus that path.')
}
for (const [name, c] of Object.entries(missCount)) {
  if (c === work.length) return { started: false, reason: '{{' + name + '}} resolves to nothing for every item (typo in the field path?)', next: USAGE }
  templateWarnings.push('{{' + name + '}} was empty for ' + c + ' of ' + work.length + ' items')
}
templateWarnings.forEach(w => log('template: ' + w))
log('fanout: ' + work.length + ' item(s) x ' + agentType + (model ? '/' + model : '') + (effort ? '/' + effort : '') + (schema ? ', structured' : ', free text') + ', retry ' + retry + ', full outputs in ' + outDir)

// ---------------------------------------------------------------------------- map
let budgetSkips = 0
async function first(w) {
  const r = await call(w.prompt, { label: agentType + ' ' + (w.index + 1) + '/' + total + ' ' + w.ref, phase: 'Map', agentType, model, effort, schema })
  return { ...w, attempts: 1, value: r.value, error: r.error }
}
async function again(prev) {
  let cur = prev
  while (cur.error && cur.attempts <= retry) {
    if (budget.total && budget.remaining() < RETRY_MIN_BUDGET) { budgetSkips++; cur = { ...cur, error: cur.error + '; retry skipped (token budget)' }; break }
    const r = await call(cur.prompt, { label: 'retry ' + cur.attempts + ' ' + agentType + ' ' + (cur.index + 1) + '/' + total + ' ' + cur.ref, phase: 'Retry', agentType, model, effort, schema })
    cur = { ...cur, attempts: cur.attempts + 1, value: r.value, error: r.error ? (r.error + ' (attempt ' + (cur.attempts + 1) + ')') : null }
  }
  return cur
}

phase('Map')
const out = await pipeline(work, first, again)

// ---------------------------------------------------------------------------- collate (input order)
const results = []
const failed = []
out.forEach((o, i) => {
  const w = work[i]
  if (!o) { failed.push({ index: w.index, ref: w.ref, attempts: 0, reason: 'pipeline stage threw' }); return }
  if (o.error) failed.push({ index: o.index, ref: o.ref, attempts: o.attempts, reason: o.error })
  else {
    const long = typeof o.value === 'string' && o.value.length > RESULT_CAP
    results.push({ index: o.index, ref: o.ref, attempts: o.attempts, file: o.out, result: long ? clip(o.value, RESULT_CAP) + ' [clipped; full output in ' + o.out + ']' : o.value })
  }
})
results.sort((a, b) => a.index - b.index)
failed.sort((a, b) => a.index - b.index)
if (budgetSkips) log(budgetSkips + ' retr' + (budgetSkips === 1 ? 'y' : 'ies') + ' skipped because the token budget was nearly spent')
const retried = results.filter(r => r.attempts > 1).length
log('fanout done: ' + results.length + ' ok (' + retried + ' after retry), ' + failed.length + ' failed, ' + skipped.length + ' capped, of ' + total)

return {
  started: true,
  agentType,
  outDir,
  structured: !!schema,
  total,
  attempted: work.length,
  succeeded: results.length,
  results,
  failed,
  skipped,
  template_warnings: templateWarnings,
}
