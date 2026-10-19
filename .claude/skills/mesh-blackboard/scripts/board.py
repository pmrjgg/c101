#!/usr/bin/env python3
"""Blackboard helper for mesh-router (stdlib only, Python 3.9+).

Layout (see ../SKILL.md):
  .stack/blackboard/<task-id>/GOAL.md  board.md  rounds.json  posts/NNNN-<agent>-<type>.md  FINAL.md

Commands:
  init  DIR --goal TEXT [--criteria "c1" "c2" ...] [--participants a b ...]
  index DIR [--round R]     validate posts, regenerate the board.md index, print a JSON summary
                            (open items, criteria met, quiescent/stalled flags); with --round
                            also records that round's stats in rounds.json. Snapshots every new
                            post into DIR/.snap/ and reports posts edited after filing.
                            stalled ignores the seed round 0: open_after(r) >= open_after(r-2) > 0
                            over rounds >= 1, with posts still being written
  ids   DIR --agents a b c [--block 10]   allocate disjoint id blocks after the highest used id
  set   DIR ID STATUS       change one post's status (router only)
  open  DIR [--to AGENT]    list open items (optionally only those addressed to AGENT)

Only the router runs `set` and `index`; participants only create new post files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

TYPES = {"claim", "evidence", "question", "answer", "objection", "decision"}
STATUS = {
    "claim": {"open", "contested", "supported", "rejected", "superseded"},
    "evidence": {"filed"},
    "question": {"open", "answered", "dropped"},
    "answer": {"filed", "accepted", "rejected"},
    "objection": {"open", "sustained", "overruled", "withdrawn"},
    "decision": {"final", "superseded"},
}
OPEN = {"open", "contested"}
SUBSTANTIVE = {"claim", "question", "objection"}
REQUIRED = ("id", "from", "type", "status", "round")
NAME_RE = re.compile(r"^(\d{4})-([a-z0-9-]+)-(claim|evidence|question|answer|objection|decision)\.md$")
START, END = "<!-- index:start -->", "<!-- index:end -->"


def read_fm(path: str) -> Tuple[Dict[str, object], str]:
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    fm: Dict[str, object] = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return fm, "\n".join(lines[i + 1:])
        m = re.match(r"^([A-Za-z_]+):\s*(.*?)\s*(#.*)?$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k] = v.strip("'\"")
    return {}, text


def load_posts(d: str):
    posts, problems = [], []
    pdir = os.path.join(d, "posts")
    for f in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        if not f.endswith(".md"):
            continue
        m = NAME_RE.match(f)
        fm, body = read_fm(os.path.join(pdir, f))
        if not m:
            problems.append("%s: filename must be NNNN-<agent>-<type>.md" % f)
            continue
        miss = [k for k in REQUIRED if not fm.get(k)]
        if miss:
            problems.append("%s: missing frontmatter %s" % (f, ", ".join(miss)))
            continue
        pid, typ, st = str(fm["id"]).zfill(4), str(fm["type"]), str(fm["status"])
        if pid != m.group(1):
            problems.append("%s: id %s does not match filename" % (f, pid))
        if typ not in TYPES or typ != m.group(3):
            problems.append("%s: type %r invalid or differs from filename" % (f, typ))
        elif st not in STATUS[typ]:
            problems.append("%s: status %r not allowed for %s (%s)" % (f, st, typ, "|".join(sorted(STATUS[typ]))))
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        title = next((ln for ln in lines if ln.startswith("#")), lines[0] if lines else "").lstrip("#").strip()[:90]
        refs = fm.get("refs") or []
        crit = fm.get("criteria") or []
        posts.append({"id": pid, "file": f, "from": fm["from"], "type": typ, "status": st,
                      "round": int(str(fm["round"])) if str(fm["round"]).isdigit() else 0,
                      "to": fm.get("to", ""), "refs": [str(r).zfill(4) for r in (refs if isinstance(refs, list) else [refs])],
                      "criteria": crit if isinstance(crit, list) else [crit], "title": title})
    ids = [p["id"] for p in posts]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append("duplicate id %s (%s)" % (dup, ", ".join(p["file"] for p in posts if p["id"] == dup)))
    known = set(ids)
    for p in posts:
        for r in p["refs"]:
            if r not in known:
                problems.append("%s: refs unknown post %s" % (p["file"], r))
    return posts, problems


def criteria(d: str) -> List[str]:
    try:
        text = open(os.path.join(d, "GOAL.md"), encoding="utf-8").read()
    except OSError:
        return []
    return re.findall(r"^\s*-\s*\[[ xX]\]\s*(D\d+)\b", text, re.M)


def write_index(d: str, posts: List[dict]) -> None:
    rows = ["| id | rnd | from | type | to | refs | status | crit | title |",
            "|----|-----|------|------|----|------|--------|------|-------|"]
    for p in posts:
        rows.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            p["id"], p["round"], p["from"], p["type"], p["to"] or "", ",".join(p["refs"]),
            p["status"], ",".join(p["criteria"]), p["title"].replace("|", "/")))
    path = os.path.join(d, "board.md")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else "# Board\n\n## Index\n%s\n%s\n" % (START, END)
    if START not in text or END not in text:
        text += "\n## Index\n%s\n%s\n" % (START, END)
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + START + "\n" + "\n".join(rows) + "\n" + END + tail)


def summary(d: str, posts: List[dict], problems: List[str], rnd: Optional[int]) -> dict:
    crit = criteria(d)
    met = sorted({c for p in posts if p["type"] == "decision" and p["status"] == "final" for c in p["criteria"]})
    open_items = [p for p in posts if p["status"] in OPEN]
    rpath = os.path.join(d, "rounds.json")
    rounds = json.load(open(rpath)) if os.path.exists(rpath) else {}
    if rnd is not None:
        rounds[str(rnd)] = {"posts": sum(1 for p in posts if p["round"] == rnd),
                            "new_substantive": sum(1 for p in posts if p["round"] == rnd and p["type"] in SUBSTANTIVE),
                            "open_after": len(open_items)}
        with open(rpath, "w") as fh:
            json.dump(rounds, fh, indent=1, sort_keys=True)
    rs = sorted(int(k) for k in rounds)
    quiescent = len(rs) >= 2 and all(rounds[str(r)]["new_substantive"] == 0 for r in rs[-2:])
    # Round 0 holds only the seed questions and round 1 always adds claims, so comparing against
    # round 0 would flag nearly every mesh at round 2. Stall = no fall over 2 rounds after round 1.
    work = [r for r in rs if r >= 1]
    stalled = (len(work) >= 3 and rounds[str(work[-1])]["open_after"] >= rounds[str(work[-3])]["open_after"] > 0
               and rounds[str(work[-1])]["posts"] > 0)
    by_type: Dict[str, int] = {}
    for p in posts:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    return {"posts": len(posts), "by_type": by_type, "max_id": max([p["id"] for p in posts], default="0000"),
            "open": [{"id": p["id"], "type": p["type"], "from": p["from"], "to": p["to"], "title": p["title"]} for p in open_items],
            "criteria": crit, "criteria_met": met, "criteria_unmet": [c for c in crit if c not in met],
            "all_criteria_met": bool(crit) and all(c in met for c in crit),
            "rounds": rounds, "quiescent": quiescent, "stalled": stalled, "problems": problems}


def cmd_init(a) -> int:
    d = a.dir
    os.makedirs(os.path.join(d, "posts"), exist_ok=True)
    goal = os.path.join(d, "GOAL.md")
    if not os.path.exists(goal):
        crit = "\n".join("- [ ] D%d: %s" % (i, c) for i, c in enumerate(a.criteria or ["<criterion>"], 1))
        parts = "\n".join("- %s: <scope / authority>" % p for p in (a.participants or ["<agent>"]))
        with open(goal, "w", encoding="utf-8") as fh:
            fh.write("# Goal\n\n%s\n\n## Done criteria\n%s\n\n## Participants\n%s\n\n"
                     "## Budget\n- max_rounds: 6\n- max_posts: 60\n- words_per_post: 400\n\n"
                     "## Glossary\n- <term>: <meaning, units>\n\n## Authority\n- <sub-question>: <agent whose word wins and why>\n"
                     % (a.goal, crit, parts))
    board = os.path.join(d, "board.md")
    if not os.path.exists(board):
        with open(board, "w", encoding="utf-8") as fh:
            fh.write("# Board: %s\n\nRouter-owned. Participants never edit this file.\n\n"
                     "## Round log\n| round | routed (agent: post ids) | id blocks | new posts | open after |\n"
                     "|-------|---------------------------|-----------|-----------|------------|\n\n"
                     "## Index\n%s\n%s\n" % (os.path.basename(os.path.normpath(d)), START, END))
    print(json.dumps({"dir": d, "goal": goal, "board": board}))
    return 0


def _sans_status(text: str) -> str:
    return re.sub(r"(?m)^status:.*\n?", "", text, count=1)


def snapshot(d: str, posts: List[dict], problems: List[str]) -> None:
    """Copy each new post to DIR/.snap/ once; flag posts whose text changed since (status excepted)."""
    sdir = os.path.join(d, ".snap")
    os.makedirs(sdir, exist_ok=True)
    for p in posts:
        src, dst = os.path.join(d, "posts", p["file"]), os.path.join(sdir, p["file"])
        cur = open(src, encoding="utf-8").read()
        if not os.path.exists(dst):
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(cur)
        elif _sans_status(open(dst, encoding="utf-8").read()) != _sans_status(cur):
            problems.append("%s: edited after filing; restore with cp %s/.snap/%s %s/posts/" % (p["file"], d, p["file"], d))


def cmd_index(a) -> int:
    posts, problems = load_posts(a.dir)
    snapshot(a.dir, posts, problems)
    write_index(a.dir, posts)
    print(json.dumps(summary(a.dir, posts, problems, a.round), indent=1))
    return 1 if problems else 0


def cmd_ids(a) -> int:
    posts, _ = load_posts(a.dir)
    nxt = max([int(p["id"]) for p in posts], default=0) + 1
    out = {}
    for i, ag in enumerate(a.agents):
        lo = nxt + i * a.block
        out[ag] = ["%04d" % lo, "%04d" % (lo + a.block - 1)]
    print(json.dumps(out))
    return 0


def cmd_set(a) -> int:
    pid = a.id.zfill(4)
    pdir = os.path.join(a.dir, "posts")
    for f in sorted(os.listdir(pdir)):
        if f.startswith(pid + "-"):
            path = os.path.join(pdir, f)
            fm, _ = read_fm(path)
            typ = str(fm.get("type", ""))
            if a.status not in STATUS.get(typ, set()):
                print("status %r not allowed for %s" % (a.status, typ), file=sys.stderr)
                return 2
            text = open(path, encoding="utf-8").read()
            new, n = re.subn(r"(?m)^status:.*$", "status: %s" % a.status, text, count=1)
            if not n:
                print("no status line in %s" % f, file=sys.stderr)
                return 2
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
            snap = os.path.join(a.dir, ".snap", f)
            if os.path.exists(snap):  # keep the snapshot's status current so a restore keeps it
                stext = open(snap, encoding="utf-8").read()
                with open(snap, "w", encoding="utf-8") as fh:
                    fh.write(re.sub(r"(?m)^status:.*$", "status: %s" % a.status, stext, count=1))
            print(json.dumps({"id": pid, "file": f, "status": a.status}))
            return 0
    print("no post with id %s" % pid, file=sys.stderr)
    return 2


def cmd_open(a) -> int:
    posts, _ = load_posts(a.dir)
    for p in posts:
        if p["status"] in OPEN and (not a.to or p["to"] in (a.to, "any", "")):
            print("%s %-9s %-24s -> %-24s %s" % (p["id"], p["type"], p["from"], p["to"] or "-", p["title"]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("dir"); p.add_argument("--goal", required=True)
    p.add_argument("--criteria", nargs="*"); p.add_argument("--participants", nargs="*"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("index"); p.add_argument("dir"); p.add_argument("--round", type=int); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("ids"); p.add_argument("dir"); p.add_argument("--agents", nargs="+", required=True)
    p.add_argument("--block", type=int, default=10); p.set_defaults(fn=cmd_ids)
    p = sub.add_parser("set"); p.add_argument("dir"); p.add_argument("id"); p.add_argument("status"); p.set_defaults(fn=cmd_set)
    p = sub.add_parser("open"); p.add_argument("dir"); p.add_argument("--to"); p.set_defaults(fn=cmd_open)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
