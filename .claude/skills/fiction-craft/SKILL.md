---
name: fiction-craft
description: "Fiction craft hub for novels and short stories: scene and sequel, goal-conflict-outcome, point of view and psychic distance, tense, voice, dialogue, pacing and tension, chapter openings and endings, when telling beats showing, genre expectations, and manuscript conventions, with a routing table to the manuscript-project, copyediting, prose-style-analysis and developmental-editing skills. Load when drafting, revising, critiquing or planning fiction."
when_to_use: "Writing or continuing a chapter or scene, revising on editorial notes, judging whether a scene works, choosing POV or tense, fixing flat dialogue or sagging pace, or deciding which writing skill or agent a fiction task needs."
---

# Fiction craft

Craft is a set of lenses, not rules. Every principle below has deliberate exceptions; name the effect
you want, then check the page delivers it. Deeper notes and examples:
[craft reference](references/craft-reference.md).

## 1. Routing

| Task | Skill | Agent |
|---|---|---|
| create, adopt, validate, restructure a project; add or reorder chapters | manuscript-project | writing-project-builder |
| draft, continue, revise chapters on notes | fiction-craft (this) + prose-style-analysis | fiction-writer |
| spelling, punctuation, grammar, name and term consistency | copyediting | copy-editor |
| show-not-tell, purple or generic prose, filter words, dialogue tags, rhythm, simplify to a grade | prose-style-analysis | prose-stylist |
| structure, plot logic, stakes, pacing, arcs, continuity, whole-book review | developmental-editing | manuscript-reviewer |
| everything at once on a finished draft | `/manuscript-review` workflow (main thread) | manuscript-reviewer synthesizes |

Order of work on a draft: developmental (global) before line style before copyedit (local). Polishing
sentences in a scene that will be cut wastes the most effort.

## 2. Scene and sequel

A **scene** is a unit of change: someone wants something now, meets opposition, and the situation
ends different. A **sequel** is the reaction: emotion, thought about the dilemma, decision that
launches the next goal.

| Part | Question the page must answer | Failure sign |
|---|---|---|
| Goal | What does the viewpoint character want in this scene, concretely? | wandering, "she went to the market and thought about things" |
| Conflict | What stands in the way, and does it escalate? | obstacles solved on the first try |
| Outcome | No, yes-but, or no-and-worse (plain yes kills tension) | scene ends where it began |
| Reaction | How does it land emotionally? | character unaffected by what happened |
| Dilemma | What are the bad options? | an obvious next move |
| Decision | What will she do now? | the next scene starts without motive |

Test any scene: delete it in your head. If nothing later breaks, it either needs a change or a cut.
Sequels can be one paragraph; thrillers compress them, literary fiction expands them.

## 3. Point of view and psychic distance

| POV | Gains | Costs | Watch for |
|---|---|---|---|
| first person | intimacy, voice | only what the narrator knows | narrator explaining what they could not know |
| close third | intimacy with flexibility | one head per scene | head-hopping mid-scene |
| multiple close third | scope | reader re-anchoring each switch | switch without a scene break; indistinct voices |
| omniscient | authority, irony | distance, harder to sustain | drifting into close third and back by accident |
| second person | strangeness, address | fatigue over length | inconsistency with "I" |

Psychic distance runs from far ("It was winter of 1994. A woman crossed the marsh.") to near ("God,
the cold. She'd never make it."). Move along it on purpose: zoom out for transitions and setting,
in for emotional peaks. Each POV scene opens by anchoring who, where and when within the first three
paragraphs. One viewpoint per scene unless the book is omniscient; a switch needs a scene break
(blank line or `* * *`).

## 4. Tense

Past is invisible; present is immediate and narrows reflection. Choose once per book (front matter
`tense`) and enforce: flashbacks in past-tense books take two or three sentences of past perfect
("she had walked"), then simple past, then a past-perfect exit. Present-tense books use simple past
for backstory. Accidental slips are copyedit findings; deliberate shifts need a visible reason.

## 5. Voice

Voice is diction + syntax + what the narrator notices + what they refuse to say. Keep a voice note per
viewpoint character in `style-sheet.md` (word stock, sentence length, metaphors drawn from their
world, verbal tics). A fisherman's metaphors come from nets and weather, not from opera. Test: cover
the name tags; can you tell who is talking or narrating?

## 6. Dialogue

- Every exchange does at least two jobs: advance plot, reveal character, raise tension, deliver
  information the reader needs at that moment.
- Subtext: people rarely say what they mean when it matters. Let the reader infer; do not add a line
  explaining what was meant.
- Tags: `said` and `asked` disappear; action beats ("She set the cup down.") identify and pace.
  Adverb tags and said-bookisms ("he hissed", "she chortled") are flagged in prose-style-analysis.
- Cut greetings, small talk and full names in address unless they characterize.
- "As you know, Bob" exposition (characters telling each other what both know) is a high finding.
- Dialect by syntax and word choice, not phonetic spelling.

## 7. Pacing and tension

| Lever | Faster | Slower |
|---|---|---|
| sentence and paragraph length | short | long |
| ratio of scene to summary | more scene, less summary of time | more summary, reflection |
| dialogue ratio | higher | lower |
| white space | more breaks | dense blocks |
| information | withheld (questions open) | delivered (questions closed) |

Tension = a question the reader wants answered + uncertainty about the answer. Close one question
only after opening another. Micro-tension on every page: friction between characters, a small
unknown, a wrong note. Pacing map from data: `manuscript.py stats` gives words and dialogue ratio per
chapter (developmental-editing turns it into a map).

## 8. Openings and endings

Chapter opening, first page: anchor POV, place, time; a disturbance or a question within the first
page; no weather or waking-up openings unless they are the disturbance. Book opening: voice + a
character wanting something + a world slightly off balance.

Chapter ending: end on a turn, a decision, a question or an image that recharges, not on the
character falling asleep or a summary of what was learned. Book ending: the central question
answered in action, the arc completed or deliberately denied, a final image echoing the opening.

## 9. Show and tell: when each is right

Show (dramatize in scene, concrete sensory detail, action, dialogue) when the moment matters
emotionally or changes something. Tell (summary, named feeling, compressed time) when:

| Telling is right for | Example |
|---|---|
| transitions and time jumps | "Three winters passed before she went back." |
| routine actions the reader can supply | "She showered and drove to work." |
| background a scene would bloat | one paragraph of family history |
| pace control after a big scene | a short sequel paragraph |
| deliberate narrator voice (omniscient, retrospective first person) | "I was a coward then, and I knew it." |

Telling is wrong when it replaces a scene the reader was promised, names an emotion the scene already
showed (double-telling), or explains subtext ("She was angry, which was really fear.").

## 10. Genre expectations (lenses)

| Genre | Reader contract | Typical length (words) |
|---|---|---|
| thriller / suspense | rising stakes, ticking clock, short chapters, reversals | 70k-100k |
| mystery | fair-play clues, suspects, solution earned from planted evidence | 70k-90k |
| romance | central relationship, emotional beats, optimistic ending (HEA/HFN) | 50k-100k |
| fantasy / SF | coherent rules of the world, cost to magic or tech, wonder | 90k-130k |
| literary | interiority, language, ambiguity tolerated, change may be internal | 70k-100k |
| horror | dread, escalation, vulnerability | 60k-90k |
| YA | teen protagonist, present urgency, voice, coming of age | 50k-80k |
| middle grade | protagonist ~10-13, clear stakes, simpler syntax (grade 4-7) | 30k-55k |

More detail per genre in [craft reference](references/craft-reference.md). Breaking a contract is
allowed when the book signals it early.

## 11. Manuscript conventions

- One chapter per file, `# Title` first, prose after; scene breaks as a blank line plus `* * *` on
  its own line (or the project's style-sheet marker).
- Paragraphs separated by one blank line; no hard wraps inside paragraphs (anchors stay stable).
- Italics with `*...*`; no bold in prose; no HTML except the chapter-list markers.
- Dialogue: a new paragraph for each new speaker; action beats sit in the speaker's paragraph.
- The project's `style-sheet.md` overrides every default here; the `language` key in
  `manuscript.md` picks spelling and punctuation rules (copyediting).

## 12. Worked example: fixing a flat scene

Draft: "Mara went to see Tomas. She was nervous. They talked about the letter and he was angry. She
felt bad and left."

Diagnosis: no goal, named emotions (tell), conflict summarized, outcome unclear, no sequel.

Revision plan: goal (get Tomas to admit he read the letter); conflict (he deflects with chores, then
turns it on her); outcome no-and-worse (he burns the letter); reaction in one beat; decision (she will
go to the surveyor).

> Tomas didn't look up from the net. "Tide's turning."
> "You opened it." She laid the envelope on the bench between them, flap up.
> His hands kept working the knot. "You going to tell me what's in it, or do I have to read it again?"

The anger now lives in the knot and the deflection; nothing is named.

## 13. Before you return a chapter

- [ ] Each scene has a goal, opposition and a changed outcome; each chapter ends on a turn.
- [ ] POV anchored early; no head-hopping; tense consistent with front matter.
- [ ] Voice matches the style-sheet notes for the viewpoint character.
- [ ] No canon contradictions with `bible/`; new facts listed.
- [ ] Prose self-check run (prose-style-analysis, `prose_check.py style`), high flags fixed or justified.
