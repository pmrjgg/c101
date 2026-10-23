#!/usr/bin/env node
// Dry-run a saved workflow script with a mocked runtime: no model calls, no tokens.
// Checks argument validation, control flow, phase/label usage and the shape of the return value.
//
//   node wf_harness.js .claude/workflows/<name>.js [--args '<json>'] [--fixtures fixtures.json] [--quiet]
//
// fixtures.json maps an agentType (or a label prefix, tried first) to the value agent() returns:
//   { "fact-checker": {"verdict": "supported", "sources": [{"url": "https://example.org"}]},
//     "adversarial-verifier": [{"refuted": false, "reason": "ok"}, {"refuted": true, "reason": "no source"}],
//     "label:check #3": null }
// An array is served round-robin; null simulates a skipped or dead agent. Unmatched calls return
// {} when a schema was given, else the string "ok".
// Exit codes: 0 ran, 1 script threw, 2 usage error.
'use strict'
const fs = require('fs')

const argv = process.argv.slice(2)
if (!argv.length || argv[0].startsWith('-')) {
  console.error('usage: node wf_harness.js <workflow.js> [--args JSON] [--fixtures FILE] [--quiet]')
  process.exit(2)
}
const file = argv[0]
let argsVal
let fixtures = {}
let quiet = false
for (let i = 1; i < argv.length; i++) {
  if (argv[i] === '--args') argsVal = argv[++i]
  else if (argv[i] === '--fixtures') fixtures = JSON.parse(fs.readFileSync(argv[++i], 'utf8'))
  else if (argv[i] === '--quiet') quiet = true
  else { console.error('unknown option ' + argv[i]); process.exit(2) }
}
// Pass args the way the runtime does: parsed JSON value when it parses, else the raw string.
let args
if (argsVal !== undefined) { try { args = JSON.parse(argsVal) } catch (e) { args = argsVal } }

const src = fs.readFileSync(file, 'utf8')
if (!/^\s*export\s+const\s+meta\s*=/.test(src)) { console.error('first statement must be export const meta = {...}'); process.exit(1) }
const body = src.replace(/export\s+const\s+meta\s*=/, 'const meta =')
function extractMeta(s) {
  const m = s.match(/export\s+const\s+meta\s*=\s*/)
  const i = s.indexOf('{', m.index)
  let d = 0, q = null
  for (let j = i; j < s.length; j++) {
    const c = s[j]
    if (q) { if (c === '\\') { j++; continue } if (c === q) q = null; continue }
    if (c === '"' || c === "'" || c === '`') { q = c; continue }
    if (c === '{') d++
    else if (c === '}') { d--; if (!d) return (new Function('return (' + s.slice(i, j + 1) + ')'))() }
  }
  return null
}
let meta = null
try { meta = extractMeta(src) } catch (e) { console.error('meta literal does not evaluate: ' + e.message); process.exit(1) }

const calls = []
const logs = []
const phases = []
const rr = {}
function pick(key) {
  const v = fixtures[key]
  if (!Array.isArray(v)) return v
  rr[key] = (rr[key] || 0) + 1
  return v[(rr[key] - 1) % v.length]
}
async function agent(prompt, opts) {
  opts = opts || {}
  const rec = { label: opts.label || null, agentType: opts.agentType || '(workflow default)', phase: opts.phase || phases[phases.length - 1] || null,
    model: opts.model || null, effort: opts.effort || null, schema: !!opts.schema, promptChars: String(prompt).length }
  calls.push(rec)
  if (!opts.label) rec.warn = 'no label'
  if (!opts.phase) rec.warn = (rec.warn ? rec.warn + '; ' : '') + 'no phase'
  if (!opts.agentType) rec.warn = (rec.warn ? rec.warn + '; ' : '') + 'no agentType'
  if (opts.label && ('label:' + opts.label) in fixtures) return pick('label:' + opts.label)
  if (opts.agentType && opts.agentType in fixtures) return pick(opts.agentType)
  return opts.schema ? {} : 'ok'
}
async function parallel(thunks) {
  return Promise.all(thunks.map(async t => { try { return await t() } catch (e) { logs.push('parallel thunk threw: ' + e.message); return null } }))
}
async function pipeline(items, ...stages) {
  return Promise.all(items.map(async (item, i) => {
    let v = item
    for (const s of stages) {
      try { v = await s(v, item, i) } catch (e) { logs.push('pipeline item ' + i + ' dropped: ' + e.message); return null }
    }
    return v
  }))
}
function phase(t) { phases.push(t) }
function log(m) { logs.push(String(m)) }
const budget = { total: null, spent: () => 0, remaining: () => Infinity }
async function workflow() { throw new Error('workflow() is not simulated by the harness') }

;(async () => {
  let result
  try {
    const AF = Object.getPrototypeOf(async function () {}).constructor
    const fn = new AF('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
    result = await fn(agent, parallel, pipeline, phase, log, args, budget, workflow)
  } catch (e) {
    console.error('SCRIPT THREW: ' + (e && e.stack ? e.stack : e))
    process.exit(1)
  }
  const warnings = calls.filter(c => c.warn).map(c => (c.label || c.agentType) + ': ' + c.warn)
  if (result === undefined) warnings.push('script returned undefined (return a structured object)')
  else if (typeof result === 'string') warnings.push('script returned a string (return a structured object)')
  const used = [...new Set(phases.concat(calls.map(c => c.phase).filter(Boolean)))]
  const declared = ((meta && meta.phases) || []).map(p => p.title)
  for (const p of used) if (declared.length && !declared.includes(p)) warnings.push('phase "' + p + '" is not in meta.phases')
  if (!meta || !meta.name || !meta.description) warnings.push('meta needs name and description')
  const out = { meta: meta && meta.name, agentCalls: calls.length, byAgentType: {}, phasesUsed: used, phasesDeclared: declared, logs, warnings, result }
  for (const c of calls) out.byAgentType[c.agentType] = (out.byAgentType[c.agentType] || 0) + 1
  if (!quiet) out.calls = calls
  console.log(JSON.stringify(out, null, 2))
})()
