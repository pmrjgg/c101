---
name: chart-design-encoding
description: "Data-visualisation design: chart form chosen by question, perceptual encoding ranking, categorical/sequential/diverging colour, axis/label/annotation rules, uncertainty, small multiples, dashboards and publication figures, styled in matplotlib, Vega-Lite or Observable Plot. Load before designing or critiquing any chart, figure or dashboard."
when_to_use: "Choosing a chart type for a question, critiquing or redesigning a chart (pie, 3D, dual axis, rainbow colour map, truncated bars), picking categorical, sequential or diverging colours, error bars and confidence bands, small multiples, KPI dashboards, journal figure sizes and fonts, alt text for charts, or styling matplotlib, Vega-Lite or Observable Plot output."
---

# Chart design and encoding

A chart is done when its title states the finding, its form fits the question, the comparison
that matters sits on the most accurate channel (aligned position or length), colour has a job and
survives a CVD check, uncertainty and n are labelled, and the export fits the medium.

Procedure: write the question and the one finding → pick the form (1) → encode (2) → colour (3)
→ axes and labels (4) → annotation (5) → uncertainty (6) → facets or dashboard (7, 8) → style and
export (9, 10) → accessibility (11) → score with the rubric (12) and fix the lowest rows.

## 1. Question to form

| Question | Use | Avoid | Notes |
|---|---|---|---|
| Comparison across categories | sorted bars (horizontal for long labels), dot plot | unsorted bars, radar, pie | dot plot when zero is not meaningful or there are many categories |
| Trend over time | line; bars for a few discrete periods | pie series, 3D, area stacks of many series | area only for a single total |
| Distribution | histogram (state the bin width), box, violin (with box or points), ECDF | bar of means | ECDF compares distributions without binning choices |
| Relationship | scatter with a trend line and its band | lines through unordered x | hexbin or 2D density above ~5k points |
| Part-to-whole | stacked bar (100 % when shares matter), treemap for many or nested parts | 3D pie, pies with 5+ parts, several pies to compare | pie or donut only for 2-4 parts of a meaningful whole |
| Ranking | lollipop or sorted bar; slope chart for rank change between two dates | unsorted order | |
| Geography | choropleth of rates (per capita, per 100k), classed sequential scale | choropleth of raw counts (it maps population) | proportional symbols for counts |
| Single headline value | big number + delta + period + sparkline | gauge, dial | |

## 2. Encoding ranking (Cleveland and McGill 1984)

Accuracy of quantitative judgement, best first:

1. Position along a common, aligned scale.
2. Position along identical but unaligned scales.
3. Length.
4. Angle and slope (direction).
5. Area (volume and curvature come below area).
6. Colour saturation or lightness (shading). Hue carries categories, not quantities.

Consequences:

- Bars encode length, so the value axis starts at zero; a truncated bar axis lies. Lines encode
  position and slope, so a line's y axis may start elsewhere; label the range.
- No 3D: perspective distorts length, angle and area and hides marks behind others.
- No dual axes without a clear justification: two arbitrary scales make crossings and relative
  slopes meaningless. Use two aligned panels sharing x, or index both series to 100 at a base
  date. Acceptable: one quantity in two units (°C and °F).
- Stacked bars: only the bottom segment sits on a common baseline; put the key series at the base
  or use small multiples.
- Bubbles: area proportional to value (radius ∝ √value), never radius ∝ value.

## 3. Colour

- Categorical, at most 7 hues. Okabe-Ito: #E69F00 orange, #56B4E9 sky blue, #009E73 bluish
  green, #F0E442 yellow, #0072B2 blue, #D55E00 vermillion, #CC79A7 reddish purple, #000000.
  Tableau 10: #4E79A7 #F28E2B #E15759 #76B7B2 #59A14F #EDC948 #B07AA1 #FF9DA7 #9C755F #BAB0AC
  (more than 7 shown at once is too many: group into "Other", facet or label directly).
- Measured on white: Okabe-Ito orange 2.25:1, sky blue 2.31:1 and yellow 1.32:1 fall under the
  3:1 that thin lines and small marks need; give them a darker outline, use them as large fills
  with labels, or put the chart on a dark surface. Blue 5.18, vermillion 3.87, bluish green 3.42
  and reddish purple 3.06 pass.
- Sequential: perceptually uniform only: viridis, cividis (designed for CVD), or a single-hue
  OKLCH ramp with L from about 0.95 to 0.35 (`oklch-palette-ramps`); darker = more on light
  backgrounds.
- Diverging: only around a meaningful midpoint (zero, target, 100 %, national average); two hues,
  a light neutral midpoint, symmetric limits.
- Never rainbow or jet: non-monotonic lightness invents boundaries, hides real ones and fails CVD
  and grayscale.
- Highlight one series, gray the rest: accent for the subject, gray for context, the highlighted
  label set in the accent colour or bold. Gray marks that carry data need 3:1 against the
  background: #949494 on white measures 3.03:1.
- CVD check every palette (the `visual-accessibility-audit` CVD command, Machado 2009
  simulation): series that must be told apart differ by at least 0.10-0.15 OKLCH L under every
  simulation, or carry direct labels, shapes or patterns. Measured: highlight #0072B2 against gray
  #949494 keeps ΔL ≥ 0.10 under protan, deutan, tritan and grayscale (protan is borderline at
  0.10), so the highlight also gets a bold label.

## 4. Axes, labels, ticks

- Direct labels at line ends or bar ends instead of a legend; a legend only when more than 4
  series cannot be labelled, ordered like the data.
- Units in the axis title or subtitle ("Revenue (USD m)"), not on every tick (except %).
- 5-7 ticks on nice numbers (1, 2, 5 × 10ⁿ); light gridlines (#E5E5E5) behind the data; no frame.
- Numbers: thousands separators (12,480), SI prefixes (12.5k, 3.2M; say "bn" for finance
  readers), consistent decimals, a true minus sign (−), % without decimals unless they matter.
- Log scales: say "log scale" on the axis, ticks at powers of 10 or 1-2-5 with readable labels
  (10, 100, 1k); never for values ≤ 0.
- Dates: one format per chart, no repeated years, label the period end for period data.
- Aspect ratio: bank to 45°. With median absolute segment slope m (data units) and ranges Rx, Ry,
  the median segment draws at 45° when height / width = Ry / (m · Rx); clamp to the layout.

```python
import numpy as np
def banked_aspect(x, y):                       # height / width that banks slopes to 45 degrees
    s = np.abs(np.diff(y) / np.diff(x)); m = np.median(s[s > 0])
    return np.ptp(y) / (m * np.ptp(x))
```

## 5. Annotation layer

| Element | Rule | Example |
|---|---|---|
| Title | states the finding, sentence case, about 12 words max | "Chat tickets doubled after the July launch" (not "Tickets by channel") |
| Subtitle | scope, units, period, population, n | "Support tickets per week, all regions, Jan-Sep 2026 (n = 12,480)" |
| Event annotations | thin rule plus short label anchored to the data, 3 at most | "Pricing change, 1 Jun" |
| Source and notes | bottom left, smaller and muted | "Source: helpdesk export, 1 Oct 2026. Excludes spam (3 %)." |

Reading order to design for: title → highlighted mark → annotation → axes → source.

## 6. Uncertainty

- Say what the bars show: "error bars: 95 % CI (bootstrap, 2,000 resamples)", "±1 SD" or "±1 SE".
  SD describes the spread of the data; SE and CI describe the precision of an estimate; ±1 SE is
  roughly a 68 % interval.
- Series get bands (fill at 15-25 % opacity under the line), not a bar at every point.
- Show n per group ("Group A (n = 48)").
- No bar plus error bar ("dynamite plot") for distributions: it hides shape, n and outliers. Use
  points (jittered strip or beeswarm) with mean ± CI, a box or a violin.
- Forecasts: fan chart with 50/80/95 % bands; actual solid, forecast dashed.
- Overlapping 95 % CIs do not prove "no difference" (two estimates can differ significantly while
  their intervals overlap); test the difference itself.

## 7. Overlays versus small multiples

- Up to 4 series: overlay with direct labels. More than 4: small multiples with shared x and y
  scales (free scales only when the question is shape, and then say "scales differ").
- Sort facets by the quantity of interest (latest value, growth, peak), not alphabetically;
  keep natural orders (time, ordinal categories, geography); "Other" or "Total" goes last.
- Ghosting: draw every series in light gray in each panel and the panel's own series in colour.
- One row of panels to compare y, one column to compare x; up to about 4 × 4; axis labels on the
  outer panels only.

## 8. Dashboards

- KPI tile row: value, delta against a stated comparison (absolute and %), the period, a direction
  arrow plus colour (never colour alone), optional sparkline.
- 2-3 key charts above the fold answering the primary questions; details below.
- One time window per view, stated on every tile; one colour per category across all charts.
- Global filters top left, with the current state visible and a reset.
- Stated freshness: "Data as of 2026-10-19 06:00 UTC, refreshed daily".
- No gauges, dials or 3D; about 7 charts per view at most; a 12-column grid with KPI tiles of 3.

## 9. Styling snippets and export

matplotlib (`pdf.fonttype` 42 keeps text editable TrueType in PDF and PS; `svg.fonttype: none`
keeps SVG text as text):

```python
import matplotlib as mpl
from cycler import cycler
mpl.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Inter", "DejaVu Sans"], "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#E5E5E5", "grid.linewidth": 0.8,
    "lines.linewidth": 2.0, "legend.frameon": False, "savefig.bbox": "tight",
    "axes.prop_cycle": cycler(color=["#0072B2", "#D55E00", "#009E73", "#CC79A7",
                                     "#E69F00", "#56B4E9", "#000000"]),
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
})
```

Vega-Lite `config` block:

```json
{"config": {
  "font": "Inter", "view": {"stroke": null},
  "title": {"anchor": "start", "fontSize": 16, "fontWeight": 600, "subtitleColor": "#555555"},
  "axis": {"domain": false, "ticks": false, "gridColor": "#E5E5E5", "labelColor": "#444444",
           "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": 400, "tickCount": 6},
  "axisX": {"grid": false},
  "legend": {"orient": "top", "title": null},
  "range": {"category": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]},
  "bar": {"color": "#949494"}, "line": {"strokeWidth": 2}
}}
```

Observable Plot has no global theme; wrap `Plot.plot` with house defaults:

```js
const housePlot = (options) => Plot.plot({
  width: 640, marginLeft: 120,
  style: {fontFamily: "Inter, system-ui, sans-serif", fontSize: "12px"},
  x: {grid: true, tickFormat: "~s"}, y: {label: null}, ...options
});
housePlot({marks: [
  Plot.barX(data, {x: "tickets", y: "channel", sort: {y: "-x"},
                   fill: (d) => d.channel === "In-app widget" ? "#0072B2" : "#949494"}),
  Plot.ruleX([0])
]});
```

Export: SVG or PDF for vector output (fonts embedded or kept as text); PNG at 2× the CSS size for
raster on screens; 300-600 ppi for raster in print; never JPEG for charts.

## 10. Publication figures

- Widths: single column about 85-90 mm, double column about 170-180 mm (e.g. Nature 89 and
  183 mm); the journal's author guide wins.
- Set the figure size in final units (`figsize=(180/25.4, 70/25.4)`) and fonts in points: 7-9 pt
  text at final size; never scale the figure afterwards.
- Line widths at least 0.5 pt (axes 0.5-0.75 pt, data 1-1.5 pt).
- Vector PDF with embedded fonts (`pdf.fonttype` 42; `pdffonts` shows emb yes); heavy layers such
  as dense scatter `rasterized=True` at 300-600 ppi.
- Panel labels (a), (b): 8-9 pt bold at the top left of each panel, consistent position:

```python
fig, axs = plt.subplots(1, 2, figsize=(180 / 25.4, 70 / 25.4), layout="constrained")
for ax, tag in zip(axs, "ab"):
    ax.text(-0.12, 1.04, f"({tag})", transform=ax.transAxes, fontsize=8, fontweight="bold", va="bottom")
fig.savefig("fig2.pdf")                       # vector, Type 42 fonts
```

- CVD-safe and legible in grayscale print; colour only where it encodes something.

## 11. Accessibility

- Marks that carry data (bars, lines, points, essential gridlines) at 3:1 against adjacent colours
  (WCAG 1.4.11); chart text at 4.5:1 (1.4.3).
- Redundant encoding (1.4.1): shapes per series (circle, square, triangle), dash patterns for
  lines, hatching for fills, direct labels.
- Alt text gives the chart type, the takeaway and key numbers, and points to the data: "Horizontal
  bar chart of support tickets by channel, Q3 2026 (n = 12,480). Email leads with 3,120 (25 %);
  the in-app widget, launched in July, already handles 1,250 (10 %). Data table below." Publish the
  data as an HTML table or CSV; complex charts also get a long description.
- Interactive charts: keyboard focus on marks; tooltips are never the only route to a value.

## 12. Critique rubric

Score 0-3 per row (0 absent or misleading, 3 excellent); ship at 22/30 or more with no zero.

| Criterion | 3 means |
|---|---|
| Finding | title states the finding; answer readable in 5 seconds |
| Form | matches the question (section 1) |
| Encoding | key comparison on aligned position or length; zero baseline for bars; no 3D |
| Colour | each colour has a job; at most 7 categories; CVD-checked |
| Labels and axes | direct labels, units, 5-7 ticks, clean number format |
| Annotation | subtitle with scope and n, events marked, source line |
| Honesty and uncertainty | n shown, intervals defined, no truncation or distortion |
| Clutter | no decoration that is not data; light grid; legend only if needed |
| Accessibility | 3:1 marks, redundant cues, alt text and data table |
| Craft and export | aligned, consistent formats, vector or 2× export, fonts embedded |

## 13. Worked example: 9-slice 3D pie → sorted bar

Data: support tickets by channel, Q3 2026, n = 12,480: Email 3,120; Live chat 2,870; Phone 1,990;
Help-centre form 1,500; In-app widget 1,250; Social media 690; Partner portal 520; Community forum
330; Other 210. The in-app widget launched in July.

Before: tilted 3D pie, 9 rainbow slices with red next to green, legend on the right, one-decimal
percentages inside slices, title "Tickets by Channel Q3", no source.

| Criterion | Before | After | Change |
|---|---|---|---|
| Finding | 0 | 3 | title states the widget finding |
| Form | 0 | 3 | 9 parts → sorted horizontal bars, "Other" last |
| Encoding | 0 | 3 | angle and 3D area → length from zero |
| Colour | 0 | 3 | 9 hues → one highlight (#0072B2), context gray (#949494, 3.03:1) |
| Labels and axes | 1 | 3 | legend lookup → direct labels "1,250 (10 %)" |
| Annotation | 1 | 3 | subtitle with period and n, source line |
| Honesty and uncertainty | 1 | 2 | 3D tilt inflated front slices; still no prior-quarter context |
| Clutter | 1 | 3 | shadows, legend and slice labels removed |
| Accessibility | 0 | 3 | colour-only → bold highlighted label, alt text, data table |
| Craft and export | 1 | 2 | SVG plus 2× PNG; rounded shares sum to 101 % (footnote) |
| **Total** | **5/30** | **28/30** | ships (≥ 22, no zero) |

```python
import matplotlib.pyplot as plt
data = {"Email": 3120, "Live chat": 2870, "Phone": 1990, "Help-centre form": 1500,
        "In-app widget": 1250, "Social media": 690, "Partner portal": 520,
        "Community forum": 330, "Other": 210}
total = sum(data.values())
order = ["Other"] + sorted((k for k in data if k != "Other"), key=data.get)   # barh draws bottom-up
fig, ax = plt.subplots(figsize=(6.4, 3.6), layout="constrained")
bars = ax.barh(order, [data[k] for k in order], height=0.7,
               color=["#0072B2" if k == "In-app widget" else "#949494" for k in order])
for k, b in zip(order, bars):
    ax.text(b.get_width() + 40, b.get_y() + b.get_height() / 2, f"{data[k]:,} ({data[k] / total:.0%})",
            va="center", fontsize=9, fontweight="bold" if k == "In-app widget" else "normal")
ax.set_xlim(0, 3800); ax.xaxis.set_visible(False); ax.grid(False)
ax.spines[["left", "bottom"]].set_visible(False); ax.tick_params(axis="y", length=0)
fig.suptitle("The in-app widget, launched in July, already handles 1 in 10 tickets",
             x=0.01, ha="left", fontweight="bold")
ax.set_title("Support tickets by channel, Q3 2026 (n = 12,480)", loc="left", fontsize=10, color="#555555")
fig.supxlabel("Source: helpdesk export, 1 Oct 2026. Shares are rounded and may not sum to 100 %.",
              x=0.01, ha="left", fontsize=8, color="#555555")
fig.savefig("tickets_by_channel.svg"); fig.savefig("tickets_by_channel.png", dpi=200)
```

Remaining fix for 30/30: add the Q2 value per channel as a small gray tick on each bar so growth
is visible, and link the CSV.

## Pitfalls

- Truncated bar axes; dual axes chosen to make two lines cross; 3D anything.
- Rainbow or jet colour maps; more than 7 categorical colours; a colour meaning one thing in one
  chart and another in the next.
- Pie charts with 5+ slices; choropleths of counts; facets sorted alphabetically.
- Error bars without saying SD, SE or CI; n missing; dynamite plots.
- Topic titles ("Revenue by month") instead of findings; legends far from the data.
- Dashboard tiles with different time windows; no refresh time.
- Text converted to outlines or Type 3 fonts in PDFs; 1× PNG on high-density screens; JPEG
  artefacts on lines and text.

Related: `oklch-palette-ramps`, `visual-accessibility-audit`, `type-scale-systems`, `layout-grids-posters-editorial`, `ui-mockup-hifi`, `brand-guidelines-system`, `print-prepress-pdfx`, hub `graphic-design`
