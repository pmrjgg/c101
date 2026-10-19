# Icon metaphor conventions

Use the conventional metaphor unless the brief proves users know another. Test anything not on
this list with the 5-second test (SKILL.md section 5).

## 1. Actions

| Meaning | Convention | Avoid / note |
|---|---|---|
| Search | magnifier | binoculars, eye |
| Settings | gear (cog) | wrench (tools, maintenance), sliders (filters, adjustments) |
| Delete | trash can | X (reads as close or cancel) |
| Close, dismiss | X | trash |
| Cancel | X or circle-slash | |
| Edit | pencil | pen nib (design, drawing) |
| Add, create | plus | |
| Remove from list | minus | trash (implies permanent deletion) |
| Save document | floppy disk (still recognised) or arrow into tray | bookmark (save for later) |
| Save for later | bookmark | heart (like), star (favourite or rate) |
| Like | heart | |
| Favourite, rate | star | pick star or heart for favourites and keep it |
| Share | iOS: box with up arrow; Material: three connected nodes | follow the platform |
| Download / upload | arrow down into tray / arrow up out of tray | cloud arrows for sync only |
| Sync | two circular arrows | |
| Refresh, reload | one circular arrow | |
| Undo / redo | curved arrow left / right (mirror in RTL) | |
| Filter | funnel | |
| Sort | up and down arrows, or lines of decreasing length | |
| Menu | three horizontal lines | |
| More actions | three dots: horizontal (iOS, web) or vertical (Material) | |
| Expand / collapse | chevron down / up | plus/minus for tree nodes |
| External link | box with arrow pointing out at the top right | |
| Copy | two overlapping rectangles | |
| Paste | clipboard | |
| Attach | paperclip | |
| Link | chain links | |
| Send | paper plane (mirror in RTL) | envelope (mail, inbox) |
| Print | printer | |
| Log out | arrow leaving a door or bracket | power symbol (device power) |

## 2. Objects and states

| Meaning | Convention | Note |
|---|---|---|
| Home | house | |
| User, account | head and shoulders | |
| Group, team | two or three heads | |
| Notifications | bell | |
| Mail, inbox | envelope / tray | |
| Calendar, date | calendar page | do not print a date number unless it is live |
| Time, history | clock / clock with counter-clockwise arrow | never mirror clocks in RTL |
| Location | map pin | |
| Security, locked | closed padlock / open padlock | |
| Visibility | eye / eye with slash | |
| Information | i in a circle | |
| Warning | exclamation in a triangle | |
| Error | exclamation or X in a circle | pair with text, never colour alone |
| Success | check in a circle | |
| Help | question mark in a circle | |
| Cart, basket | shopping cart or bag (regional preference) | |
| Payment | card | avoid currency glyphs ($) in a multi-currency product |

## 3. Things to avoid

- Hand gestures (thumbs-up, OK, V sign): offensive or unclear in some regions.
- National or era-bound objects: US mailbox with flag, specific phone handsets for "call" when
  the audience is young (still widely recognised, but test).
- Animals and colours with cultural meaning (owl, pig, white flowers); religious symbols.
- Text and letters inside icons ("A" for fonts, "B" for bold in non-Latin locales, "$"): they need
  translation and break the visual language.
- Puns and brand inside jokes: zero recognition outside the team.
- Two metaphors for one action, or one metaphor for two actions (a star for both favourite and
  rating).

## 4. Recognition test protocol

1. Show each icon alone at 24 px, labels hidden, 5 seconds, in random order.
2. Ask "what happens if you click this?"; record verbatim answers.
3. Pass: 4 of 5 testers name the intended action (synonyms count). Borderline: ship with a
   visible label. Fail: change the metaphor.
4. Repeat for the 16 px variants and for the dark theme.
