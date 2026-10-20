# Generic and AI-sounding prose: catalog

The checker's `cliches` and `ai_tells` lists hold the canonical entries (in
`wordlists/en-US.json`, next to the script); this file explains the classes so you can recognize new
members the list misses. A single hit is rarely a finding; clusters and repetition across chapters
are.

## 1. Classes

| Class | Signature | Examples | Fix |
|---|---|---|---|
| stock body language | the same few gestures for every feeling | breath she didn't know she was holding; jaw clenched; heart hammered; stomach dropped; blood ran cold | a specific gesture this character makes, or cut |
| abstract wash | emotion as weather or liquid | a wave of relief washed over; dread pooled; warmth spread through her chest | concrete action or sensation |
| machine vocabulary | words statistically overused in generated text | testament, tapestry, palpable, intricate, delve, myriad, unspoken, ethereal, symphony of, dance of, whisper of, beacon, realm, embark | plain word or cut |
| hedges | softening every claim | a sense of; somehow; almost as if; seemed to; a hint of; something like | commit or cut |
| tidy triplets | three items every paragraph | cold, dark, and silent; she laughed, cried, and laughed again | two or four, or one strong one |
| moral endings | paragraph or chapter ends on an insight | And in that moment, she knew; it was then she understood; perhaps that was enough | end on an image or action |
| not-X-but-Y | symmetric contrast as a reflex | it wasn't fear, it was something deeper | state Y or show it |
| filler transitions | narrator nudges | little did she know; it was as if time stood still; all at once | cut |
| sensory checklist | one sight, sound, smell per paragraph by formula | the scent of salt, the cry of gulls, the feel of wind | keep the one sense that matters |
| over-explained subtext | narrator interprets dialogue | , his words heavy with meaning; which was his way of saying sorry | trust the line |
| even-keeled sentences | every sentence medium length, every paragraph three sentences | (rhythm check) | vary length and paragraphing |

## 2. Classic cliches (selection)

dead of night; heart of gold; cold as ice; quiet as a mouse; time stood still; at the end of the day;
in the nick of time; all hell broke loose; calm before the storm; eyes like saucers; frozen in place;
a chill ran down her spine; let out a sigh of relief; the silence was deafening; only time will tell;
every fiber of her being; a deafening roar; tears streamed down; sent shivers down; head over heels.

## 3. Judgment rules

- Dialogue: cliches characterize speakers; flag only if every character speaks in them.
- Genre idiom: hard-boiled similes, romance physical beats and thriller countdowns are expected in
  moderation; flag density, not presence.
- Subversion: a cliche turned ("cold as ice, and about as interested") is voice.
- A chapter with several classes clustered in its first and last paragraphs usually needs the
  opening and ending rewritten more than the middle.
