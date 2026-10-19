---
name: compiler-construction
description: "Building language front ends and optimisers: lexing, parser choice (Pratt, LR/LALR, ALL(*), PEG, GLR, combinators), error recovery and diagnostics, IR and SSA construction, dataflow frameworks, optimisation passes and phase ordering, instruction selection and register allocation, LLVM/MLIR/Cranelift workflows and compiler testing. Load when writing a parser, DSL, interpreter or compiler pass, or explaining surprising codegen."
when_to_use: "Writing or reviewing a lexer, parser or grammar (.y, .g4, .pest, .lalrpop, tree-sitter grammar.js) or a DSL; precedence or associativity bugs; shift/reduce conflicts; error recovery and diagnostics; designing an IR, SSA construction or a dataflow pass; reading opt output, -Rpass-missed remarks or LLVM IR; choosing between an interpreter, bytecode VM, LLVM, Cranelift or Wasm backend; fuzzing or golden-testing a compiler."
---

# Compiler construction

From characters to machine code, with the decisions that matter in practice. Language theory
(regular languages, automata, lexer DFAs) lives in `automata-regular-languages`; type checking and
inference in `type-systems-inference`; C/C++ UB detection in `cpp-ub-sanitizers`; regex practice in
`regex-engineering`. Summary facts stay in `cs-foundations` section 8.

Deep material: [SCCP on a toy SSA IR: full Python implementation and golden tests](references/sccp-example.md)

## 1. Pipeline and architecture decision

Pipeline: lex -> parse -> AST/CST -> name resolution and type checking -> lowering to IR (SSA) ->
optimisation -> instruction selection -> register allocation -> scheduling -> emission.

| Architecture | Peak speed | Startup | Effort | Choose when |
|---|---|---|---|---|
| Tree-walking interpreter | lowest | instant | days to weeks | config languages, DSLs, prototypes, teaching |
| Bytecode VM | several times a tree walker | fast | weeks to months | scripting languages, embedded runtimes |
| Existing IR: LLVM, Cranelift, Wasm (wasm-encoder, Binaryen) | near native (LLVM best peak, Cranelift much faster to compile) | LLVM slow to compile; Cranelift JIT-friendly | months | static languages, JITs (Cranelift), portable targets (Wasm) |
| Custom backend | whatever you invest | tunable | years | only with a team and a reason (Go, V8-style tiers) |

Decide by required run-time performance, startup and compile-time budget, and team size. Start one
rung lower than you think; a clean AST and IR survive a backend change.

## 2. Parser choice

| Technique | Strengths | Weaknesses | Typical users |
|---|---|---|---|
| Hand-written recursive descent + Pratt | best diagnostics and recovery, full control | manual effort, ambiguity is silent | Clang, rustc, Go, TypeScript |
| LALR(1) / LR(1) generators | linear time, conflicts reported at build time | conflicts are hard to read; weak default errors | bison, yacc, lalrpop, Menhir |
| ALL(*) | adaptive LL, direct left recursion | runtime library; slow on pathological input | ANTLR 4 |
| PEG / packrat | no ambiguity by construction, easy to write | ordered choice hides ambiguity; left recursion needs support | pest, peggy, CPython's pegen |
| GLR / Earley | any CFG, ambiguity as forests, incremental (GLR) | slower; you must disambiguate | tree-sitter (editors), bison `%glr-parser`, lark |
| Combinators | embedded in the host language, fast to iterate | errors and performance vary | nom, chumsky, megaparsec |

## 3. Pratt parsing

Each operator gets binding powers `(l_bp, r_bp)`: left-associative when `l_bp < r_bp`,
right-associative when `l_bp > r_bp`. Prefix operators have only a right power, postfix (call,
index) only a left power, and higher binds tighter.

```rust
#[derive(Debug, Clone, Copy, PartialEq)]
enum Tok { Atom(char), Op(char), Eof }
struct Lexer { toks: Vec<Tok> }
impl Lexer {
    fn new(s: &str) -> Self {
        let mut toks: Vec<Tok> = s.chars().filter(|c| !c.is_whitespace())
            .map(|c| if c.is_ascii_alphanumeric() { Tok::Atom(c) } else { Tok::Op(c) }).collect();
        toks.reverse();
        Lexer { toks }
    }
    fn next(&mut self) -> Tok { self.toks.pop().unwrap_or(Tok::Eof) }
    fn peek(&self) -> Tok { self.toks.last().copied().unwrap_or(Tok::Eof) }
}
fn prefix_bp(op: char) -> u8 { match op { '-' | '!' => 9, _ => panic!("bad prefix {op:?}") } }
fn postfix_bp(op: char) -> Option<u8> { matches!(op, '[' | '(').then_some(11) }
fn infix_bp(op: char) -> Option<(u8, u8)> {
    Some(match op {
        '=' => (2, 1),          // right-assoc
        '?' => (4, 3),          // ternary, right-assoc
        '+' | '-' => (5, 6),    // left-assoc
        '*' | '/' => (7, 8),
        '.' => (13, 14),        // member access binds tightest
        _ => return None,
    })
}
fn expr(lx: &mut Lexer, min_bp: u8) -> String {
    let mut lhs = match lx.next() {
        Tok::Atom(c) => c.to_string(),
        Tok::Op('(') => { let e = expr(lx, 0); assert_eq!(lx.next(), Tok::Op(')')); e }
        Tok::Op(op) => format!("({op} {})", expr(lx, prefix_bp(op))),
        Tok::Eof => panic!("unexpected end of input"),
    };
    loop {
        let op = match lx.peek() { Tok::Op(op) => op, Tok::Eof => break, t => panic!("bad token {t:?}") };
        if let Some(l_bp) = postfix_bp(op) {
            if l_bp < min_bp { break; }
            lx.next();
            let (close, name) = if op == '[' { (']', "index") } else { (')', "call") };
            let inner = expr(lx, 0);
            assert_eq!(lx.next(), Tok::Op(close));
            lhs = format!("({name} {lhs} {inner})");
            continue;
        }
        let Some((l_bp, r_bp)) = infix_bp(op) else { break };
        if l_bp < min_bp { break; }
        lx.next();
        lhs = if op == '?' {
            let mid = expr(lx, 0);
            assert_eq!(lx.next(), Tok::Op(':'));
            format!("(? {lhs} {mid} {})", expr(lx, r_bp))
        } else {
            format!("({op} {lhs} {})", expr(lx, r_bp))
        };
    }
    lhs
}
#[test]
fn precedence_and_associativity() {
    let p = |s: &str| expr(&mut Lexer::new(s), 0);
    assert_eq!(p("1 + 2 * 3"), "(+ 1 (* 2 3))");
    assert_eq!(p("1 - 2 - 3"), "(- (- 1 2) 3)");
    assert_eq!(p("a = b = c"), "(= a (= b c))");
    assert_eq!(p("-a[i] * b"), "(* (- (index a i)) b)");
    assert_eq!(p("a ? b : c ? d : e"), "(? a b (? c d e))");
    assert_eq!(p("f(x).y"), "(. (call f x) y)");
}
```

## 4. Grammar hygiene and lexing

- Remove left recursion for LL and PEG: `E -> E + T | T` becomes `E -> T (+ T)*`. Left-factor
  common prefixes. Encode precedence as grammar levels or bison `%left/%right/%nonassoc`.
- Dangling else: bind to the nearest `if` (LR's default shift, made explicit with `%expect` or
  `%prec`; or a matched/unmatched statement split). `bison -Wcounterexamples` prints an input that
  exhibits each conflict.
- Lexers: maximal munch (`>>=` is one token; C++11 special-cases `>>` closing templates), keywords
  beat identifiers at equal length (lex an identifier, then look it up), lexer modes with a stack
  for string interpolation (`"a ${b} c"`: push on `${`, pop at the matching `}`). DFA generators:
  re2c (C/C++), logos (Rust), flex.

## 5. Error recovery, diagnostics and syntax trees

- Panic mode: on an error, skip to a synchronising token (`;`, `}`, a statement keyword), insert an
  error node, continue. Bison's `error` token gives error productions. Report many errors per run,
  but suppress cascades: an error type that unifies with everything, one error per statement.
- Diagnostics carry spans: primary label, secondary labels, notes and a fix-it (ariadne, miette,
  codespan-reporting). Keep byte offsets in the AST and map to line/column only when printing.
- IDE and LSP work needs lossless concrete syntax trees that keep whitespace and comments: rowan
  (rust-analyzer), Roslyn-style red-green trees, tree-sitter. Formatters and refactorings depend on it.

## 6. IR and SSA

- Three-address code in basic blocks (leaders: entry, branch targets, instruction after a branch),
  forming a CFG.
- Dominators: Cooper-Harvey-Kennedy iterative algorithm over reverse postorder (simple and fast in
  practice); Lengauer-Tarjan (near-linear) for very large CFGs.
- Phi placement (Cytron et al.): for each variable, place phis at the iterated dominance frontier of
  its definition blocks, then rename in a dominator-tree preorder walk with a stack per variable.
  Pruned SSA adds a phi only where the variable is live-in. Braun et al. (2013) builds SSA on the fly
  from the AST with sealed blocks and trivial-phi removal (the approach of `cranelift-frontend`).
- Out of SSA: naive copies in predecessors break after copy propagation. Lost-copy problem: split
  critical edges or copy into a fresh temporary. Swap problem: phis at one block entry are a
  parallel copy; sequentialise with a temporary when copies form a cycle.

## 7. Dataflow framework

A lattice of facts, a meet, monotone transfer functions and a direction; iterate to the fixpoint.

| Analysis | Direction | Meet | Transfer |
|---|---|---|---|
| Reaching definitions | forward | union | gen U (in - kill) |
| Live variables | backward | union | use U (out - def) |
| Available expressions | forward | intersection | gen U (in - kill) |
| Very busy expressions | backward | intersection | use U (out - kill) |
| Constant propagation | forward | lattice meet (TOP > constant > BOT) | evaluate on known constants |

```python
from collections import deque

def solve(blocks, preds, succs, boundary, transfer, meet, top):
    """Forward; for a backward analysis swap preds/succs and use exit blocks as the boundary."""
    out = {b: top for b in blocks}
    work = deque(blocks)                       # reverse postorder converges fastest
    while work:
        b = work.popleft()
        ins = [out[p] for p in preds[b]]
        new = transfer(b, meet(ins) if ins else boundary)
        if new != out[b]:
            out[b] = new
            work.extend(s for s in succs[b] if s not in work)
    return out
```

Termination: monotone transfers over a lattice of finite height. Intervals have infinite height:
widen at loop heads (jump an unstable bound to infinity), optionally narrow afterwards.

## 8. Optimisation catalogue and order

| Pass | Needs | Notes |
|---|---|---|
| mem2reg / SROA | dominators | builds SSA from stack slots; enables almost everything |
| SCCP | SSA | constants plus unreachable code (section 13) |
| GVN / CSE | SSA, alias analysis for loads | redundancy elimination |
| DCE / ADCE | use lists | aggressive DCE assumes dead until proven live, so it removes dead cycles |
| Inlining | call graph, size and hotness cost model | unlocks local optimisations; watch code size and compile time |
| LICM | loop info, alias analysis, speculation safety | hoists invariant code |
| IndVar simplification, strength reduction | scalar evolution | canonical loops for later passes |
| Unrolling, vectorisation (loop, SLP) | trip counts, dependence analysis, cost model | read `-Rpass-missed` to see why not |
| Escape analysis / scalar replacement | interprocedural info | JVM C2/Graal, Go (`go build -gcflags=-m`) |
| Tail calls | calling convention | LLVM `musttail`, clang `[[clang::musttail]]` |
| Peephole (InstCombine-like) | none | validate every rewrite with Alive2 |
| Equality saturation | e-graph, cost-based extraction | egg/egglog; Cranelift mid-end uses ISLE rules over an aegraph |

Typical order: canonicalise early (SSA, peephole, CFG simplification), inline, iterate scalar
optimisations, loop optimisations, vectorise late, then clean up. Phase-ordering traps: inlining too
late hides constants; unrolling first can block vectorisation; canonicalisation passes fighting each
other; fixpoint iteration blowing compile time.

## 9. Backend

- Instruction selection: tree pattern matching (BURS, maximal munch tiling), LLVM SelectionDAG
  (per block) vs GlobalISel (whole function), Cranelift ISLE lowering rules.
- Register allocation: Chaitin-Briggs colouring with conservative coalescing and spilling (quality);
  linear scan (JIT speed); strict SSA interference graphs are chordal, so colouring is optimal in
  polynomial time and spilling can be decided first. LLVM uses its greedy allocator, Cranelift
  regalloc2.
- Scheduling (list scheduling on a latency model) and calling conventions (SysV x86-64 integer args in
  rdi, rsi, rdx, rcx, r8, r9; AArch64 in x0-x7; Windows x64 in rcx, rdx, r8, r9 plus shadow space).
- The UB lens: signed overflow, null dereference, strict aliasing and side-effect-free infinite loops
  let C/C++ optimisers assume facts; explain surprising codegen through them (`-fwrapv`,
  `-fno-strict-aliasing`, UBSan). Front ends for other languages must not inherit C++ assumptions
  (LLVM's `mustprogress` attribute exists for that).

## 10. Tooling commands

```bash
clang -O2 -S -emit-llvm x.c -o x.ll                                  # IR after the O2 pipeline
clang -O0 -Xclang -disable-O0-optnone -S -emit-llvm x.c -o x0.ll     # unoptimised, still optimisable
opt -passes='default<O2>' -S x0.ll -o x2.ll
opt -passes='default<O2>' -print-changed -S x0.ll -o /dev/null 2> changes.txt
opt -passes=sccp -print-after-all -S x0.ll -o /dev/null 2> trace.txt
clang -O2 -Rpass=inline -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize -c x.c
llvm-mca -mcpu=znver4 hot_loop.s                                     # throughput estimate
rustc -O --emit=llvm-ir,mir src/lib.rs                               # or: cargo rustc --release -- --emit=llvm-ir
mlir-opt in.mlir --pass-pipeline='builtin.module(func.func(canonicalize,cse))'
wasmtime explore module.wasm                                         # Wasm next to Cranelift output
```

Compiler Explorer (godbolt.org) for side-by-side compilers, flags and pass output.

## 11. Compiler testing

- Golden tests: FileCheck with lit (`; RUN:` lines, `CHECK`, `CHECK-NEXT`, `CHECK-NOT`, capture
  variables like `[[V:%[0-9]+]]` instead of hard-coded names); snapshot tests with insta
  (`cargo insta review`).
- Differential testing: run generated or real programs through your compiler and a reference
  interpreter (or another compiler) and compare outputs.
- Random program generators without UB: Csmith, YARPGen. Grammar-aware fuzzing: cargo-fuzz with
  `arbitrary`-derived ASTs, AFL++ with a grammar mutator. Reduce failures with C-Reduce/cvise or
  `llvm-reduce`.
- Verify peephole rewrites with Alive2 (`alive-tv src.ll tgt.ll`); translation validation checks
  each compilation instead of the compiler.

## 12. Pitfalls

- Regexes or string hacks for nested syntax; a PEG whose ordered choice silently prefers the wrong
  alternative (`"if" / ident` order matters), or left recursion that loops forever.
- Equal binding powers on both sides of an operator (associativity silently wrong): test both.
- Dropping spans from the AST, then producing diagnostics without locations; error cascades.
- Minimal but unpruned SSA flooding the IR with dead phis; out-of-SSA lost-copy and swap bugs.
- Non-monotone transfer functions (no termination) or interval analysis without widening.
- Emitting LLVM flags (`nsw`, `nuw`, `noundef`, `inbounds`) the source language does not justify:
  poison turns into miscompiles.
- Golden tests that pin register names or pass order details; FileCheck variables keep them stable.
- Measuring only runtime: track compile time per pass (`-ftime-report`, `-Z time-passes`).

## 13. Worked example: SCCP on a toy SSA IR

```text
entry:  x0 = const 4
        c0 = lt x0, 10
        br c0, then, else
then:   y1 = add x0, 1
        jmp join
else:   y2 = call f
        jmp join
join:   y3 = phi [then: y1], [else: y2]
        ret y3
```

Lattice per SSA value, three levels: TOP (no information yet, optimistic), a constant, BOT (not a
constant). Meet: TOP is the identity, equal constants stay, anything else falls to BOT. Values only
move down, so each changes at most twice and the analysis terminates.

Wegman-Zadeck SCCP keeps two worklists: CFG edges (a block becomes executable) and SSA edges (a
definition's value changed, so revisit its uses). Phis meet only over executable incoming edges;
uses inside unreachable blocks are ignored; a branch on a constant marks only one edge executable.

| Step | Work item | Effect |
|---|---|---|
| 1 | entry becomes executable | x0 = 4; c0 = lt(4, 10) = 1; branch on constant 1: only entry->then |
| 2 | edge entry->then | y1 = add(4, 1) = 5; edge then->join |
| 3 | edge then->join | y3 = phi over {then} = 5 |
| 4 | SSA uses of x0, c0, y1, y3 | no further change: fixpoint; `else` never executable, y2 stays TOP |

Plain constant propagation, which treats every edge as executable, would meet 5 with BOT from the
call and leave y3 = BOT; the conditional part is what proves `ret 5`.

Rewrite: replace each constant-valued instruction with `const`, turn `br c0` into `jmp then`, delete
the unreachable `else` block, drop phi operands from non-executable edges. The golden output (full
implementation and tests in [the SCCP reference](references/sccp-example.md)):

```text
entry:  x0 = const 4
        c0 = const 1
        jmp then
then:   y1 = const 5
        jmp join
join:   y3 = const 5
        ret y3
```

DCE then removes `x0`, `c0`, `y1`; CFG simplification merges the chain into `ret 5`. Cross-check
with LLVM on the equivalent IR:

```llvm
; RUN: opt -passes=sccp -S %s | FileCheck %s
declare i32 @f()
define i32 @g() {
entry:
  %c = icmp slt i32 4, 10
  br i1 %c, label %then, label %else
then:
  %y1 = add i32 4, 1
  br label %join
else:
  %y2 = call i32 @f()
  br label %join
join:
  %y = phi i32 [ %y1, %then ], [ %y2, %else ]
  ret i32 %y
}
; CHECK-LABEL: @g(
; CHECK: ret i32 5
```

Whether `sccp` alone also deletes the dead block depends on the LLVM version; run
`opt -passes='sccp,simplifycfg'` when comparing whole functions.

Related: `automata-regular-languages`, `type-systems-inference`, `regex-engineering`, `cpp-ub-sanitizers`, `rust-performance`, `rust-testing-fuzzing`, hub `cs-foundations`
