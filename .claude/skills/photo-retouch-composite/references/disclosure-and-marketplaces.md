# Disclosure rules, consent and marketplace image rules

Companion to the photo-retouch-composite SKILL.md (sections 9 and 10). Facts were checked on
2026-10-19 against official guidance where it was reachable and otherwise against law-firm and press
summaries; they are working notes, not legal advice. The caller (and their counsel) decides on
compliance: report what was changed and which rule may apply, never certify that a picture is
compliant.

## 1. Retouching and synthetic-image disclosure

| Jurisdiction | Rule | Applies to | Requirement | Notes |
|---|---|---|---|---|
| France | Code de la santé publique art. L2133-2; décret n° 2017-738 of 4 May 2017 (art. R2133-4 to R2133-6); in force since 1 Oct 2017 | commercial photographs of models whose body silhouette was made thinner or thicker with image-processing software | the mention "Photographie retouchée", accessible, easily legible and clearly separate from the advertising message | posters, online public communication, press, advertising mail and printed advertising; television advertising is not covered; the advertiser must check purchased pictures; fine of 37,500 EUR, which can rise to 30 % of the advertising spend |
| Norway | Marketing Control Act section 2, second paragraph; in force since 1 July 2022 | advertising (including paid influencer posts) in which a person's body shape, size or skin was changed by retouching or other manipulation, filters and lenses included | a standardised label designed by the authorities | supervised by the Norwegian Consumer Authority (Forbrukertilsynet), whose guideline sets the label's use and scope |
| European Union | AI Act (Regulation (EU) 2024/1689) art. 50(4); applies from 2 Aug 2026 | deployers of AI systems that generate or manipulate image content that is a "deep fake": resembling existing persons, objects, places or events and falsely appearing authentic | disclose that the content is artificially generated or manipulated | lighter duty for evidently artistic, creative, satirical or fictional works; provider-side machine-readable marking is art. 50(2) |
| General advertising law (UK CAP Code, EU unfair commercial practices rules, US FTC) | misleading-advertising rules | any advertising | retouching must not exaggerate what a product does (cosmetics: lashes, skin, hair; products: size, colour, contents) | the risk sits in the claim the picture makes, not in retouching as such |

What triggers a note to the caller (as an Open doubt or a line in the Result):

- body shape or size of a person changed by any amount (France, Norway);
- skin texture, tone or features of a person changed beyond temporary blemishes (Norway's scope
  includes skin);
- a photoreal composite or generated scene that shows real people, real places or a real product in
  a situation that did not happen (EU AI Act art. 50(4) when an AI system made or changed it);
- a product picture whose retouch changes what the buyer gets (size, colour, finish, contents).

Template:

```text
- [scope|med] Disclosure check needed - the composite places the product in an AI-generated kitchen
  scene and harmonised it with an image model; if published in the EU this may need an AI-generated
  or manipulated content disclosure (AI Act art. 50(4)) - resolve: caller decides on a label - route: user
```

## 2. Consent checklist for identifiable people

Edits that are fine without extra consent (they restore the photograph, not the person): exposure,
contrast, white balance, colour grade, crop, straightening, dust and sensor spots, stray hairs,
temporary blemishes (spots, scratches, redness), background distractions.

Edits that need consent stated by the caller (the image-editing ground rule: identity, age, body or
expression of an identifiable person never change without it):

| Edit | Why it needs consent |
|---|---|
| face or body shape, slimming or enlarging, height | changes the body; disclosure rules above |
| skin smoothing beyond temporary blemishes, wrinkle removal | changes age and skin (Norway) |
| permanent features: moles, scars, birthmarks, tattoos, teeth shape, eye colour | changes identity |
| skin tone or hair colour | changes identity |
| expression, gaze, mouth or eye opening | changes what the person did |
| placing a person into another scene or next to other people | creates an event that did not happen |

Never: alter identity documents, receipts, screenshots, evidence or news pictures to look like
something they are not; remove a person's clothing or sexualise anyone; edit minors beyond the
restoring edits above.

## 3. Marketplace main images

Amazon main (first) image, as summarised by Amazon's Seller Central rules and seller-facing guides
(check the current Seller Central page before a large batch; categories have exceptions):

| Rule | Check |
|---|---|
| pure white background, RGB 255,255,255 | `photokit.py whitebg`: `border_exact_white` 1.0 and `off_white_outside_product` 0 |
| product fills about 85 % or more of the frame | `fill_long_side` >= 0.85 (longest side of the product box over the frame side) |
| 1000 px or more on the longest side, so zoom works (more is better) | `imgcheck.py info` width and height; `expect --min-side 1000` checks the short side, so it is exact for the usual square canvas (2000x2000 is a safe default) |
| only the product for sale: no props that are not included, no text, logos, badges, borders or watermarks | Read the picture |
| the picture shows the actual product accurately | swatch check (`photokit.py swatch`, dE_OK <= 0.02 against the reference colour) and no shape edits |

Practical notes:

- Composite the cutout onto an exact white canvas (`masktool.py over cut.png white.png ...`) rather
  than levelling a grey backdrop to white: levels also bleach white product parts.
- A soft floor shadow counts as part of the product box in `whitebg`; whether a shadow is allowed
  varies by marketplace and category: ask the caller when the brief does not say.
- In tests, uniform 255 areas stayed exactly 255 through JPEG export at quality 85 and 95; re-run
  `whitebg` on the exported file anyway (resizing filters and colour-managed exports can produce 254).
- Grain added by `photokit.py grain-add` tapers to zero near pure white and pure black, so it never
  breaks the white background.
- Other marketplaces (marketplace apps, shopping ads, regional stores) publish their own image rules;
  read the current page for the target channel and record which rules were applied in the Result.
