// Dry-run harness for saved workflows (.claude/workflows/*.js).
//
//   node tests/wf_harness.mjs <workflow.js> '<args-json>' [seed]
//
// Executes the script body with stub globals that mimic the Workflow runtime:
// agent() returns a value synthesised from opts.schema (or a string), parallel()
// is a barrier that maps thrown thunks to null, pipeline() threads each item
// through its stages, and Date.now/Math.random/new Date() throw exactly like
// the real runtime. Prints one JSON line: {ok, agents, phases, logs, result|error}.
import fs from 'node:fs'

const [, , file, argsJson = 'null', seedArg = '1'] = process.argv
const src = fs.readFileSync(file, 'utf8')
let seed = Number(seedArg) || 1
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648)

const calls = []
const logs = []
const phases = []

// --- deterministic sample values from JSON Schema ---------------------------
function sample(schema, path = '', depth = 0) {
  if (!schema || depth > 8) return null
  if (schema.const !== undefined) return schema.const
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[Math.floor(rnd() * schema.enum.length)]
  const t = Array.isArray(schema.type) ? schema.type.find(x => x !== 'null') : schema.type
  if (schema.oneOf || schema.anyOf) return sample((schema.oneOf || schema.anyOf)[0], path, depth + 1)
  switch (t) {
    case 'object': {
      const o = {}
      for (const [k, v] of Object.entries(schema.properties || {})) o[k] = sample(v, path + '.' + k, depth + 1)
      return o
    }
    case 'array': {
      const n = Math.max(schema.minItems || 0, Math.min(schema.maxItems ?? 3, 3))
      return Array.from({ length: n }, (_, i) => sample(schema.items || { type: 'string' }, path + '[' + i + ']', depth + 1))
    }
    case 'integer': return Math.max(schema.minimum ?? 0, Math.min(schema.maximum ?? 5, 1 + Math.floor(rnd() * 5)))
    case 'number': {
      const lo = schema.minimum ?? 0, hi = schema.maximum ?? 1
      return lo + (hi - lo) * rnd()
    }
    case 'boolean': return rnd() > 0.5
    case 'string': return `${path.split('.').pop() || 's'}-${Math.floor(rnd() * 4)}`
    default: return null
  }
}

const g = {
  agent: async (prompt, opts = {}) => {
    if (typeof prompt !== 'string' || !prompt.length) throw new Error('agent() needs a non-empty prompt string')
    calls.push({ label: opts.label, phase: opts.phase, agentType: opts.agentType, model: opts.model, effort: opts.effort })
    if (calls.length > 1000) throw new Error('agent cap (1000) exceeded')
    if (opts.schema) {
      if (opts.schema.type !== 'object' || !opts.schema.properties) throw new Error('schema root must be an object with properties: ' + opts.label)
      for (const r of opts.schema.required || []) if (!(r in opts.schema.properties)) throw new Error(`required '${r}' not in properties (${opts.label})`)
      return sample(opts.schema, '')
    }
    return `stub text for ${opts.label || 'agent'}`
  },
  parallel: async thunks => {
    if (!Array.isArray(thunks)) throw new Error('parallel() takes an array of thunks')
    if (thunks.length > 4096) throw new Error('parallel() > 4096 items')
    return Promise.all(thunks.map(async t => {
      if (typeof t !== 'function') throw new Error('parallel() items must be thunks (functions)')
      try { return await t() } catch (e) { logs.push('parallel thunk threw: ' + e.message); return null }
    }))
  },
  pipeline: async (items, ...stages) => {
    if (!Array.isArray(items)) throw new Error('pipeline() items must be an array')
    return Promise.all(items.map(async (item, i) => {
      let v = item
      for (const s of stages) {
        try { v = await s(v, item, i) } catch (e) { logs.push('pipeline stage threw: ' + e.message); return null }
      }
      return v
    }))
  },
  phase: t => phases.push(t),
  log: m => logs.push(String(m)),
  args: JSON.parse(argsJson),
  budget: { total: null, spent: () => 0, remaining: () => Infinity },
  workflow: async () => { throw new Error('nested workflow() not stubbed') },
}

// Mimic the runtime's determinism guards.
const RealDate = Date
globalThis.Date = class extends RealDate {
  constructor(...a) { if (!a.length) throw new Error('new Date() is not allowed in workflows'); super(...a) }
  static now() { throw new Error('Date.now() is not allowed in workflows') }
}
Math.random = () => { throw new Error('Math.random() is not allowed in workflows') }

const body = src.replace(/export\s+const\s+meta\s*=/, 'const meta =')
const AF = Object.getPrototypeOf(async function () {}).constructor
let out
try {
  const fn = new AF(...Object.keys(g), body)
  const result = await fn(...Object.values(g))
  out = { ok: true, agents: calls.length, phases: [...new Set(phases)], logs, result }
} catch (e) {
  out = { ok: false, agents: calls.length, phases, logs, error: String(e && e.stack || e) }
}
process.stdout.write(JSON.stringify(out, (k, v) => (typeof v === 'string' && v.length > 400 ? v.slice(0, 400) + '…' : v)) + '\n')
