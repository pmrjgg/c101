# Extraction recipes for browser_evaluate

Functions are passed as the `function` string of `browser_evaluate`. They only read the DOM and
return JSON-serialisable values. Keep returns under about 20k tokens: paginate or slice.

## HTML table to rows

```js
() => {
  const t = document.querySelector('table');
  if (!t) return { error: 'no table' };
  const head = [...t.querySelectorAll('thead th')].map(th => th.innerText.trim());
  const rows = [...t.querySelectorAll('tbody tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => td.innerText.trim()));
  return { head, rows: rows.slice(0, 500), total: rows.length };
}
```

Several tables: select by caption or a nearby heading:
`[...document.querySelectorAll('table')].find(t => t.caption?.innerText.includes('2026'))`.

## Cards or list items

```js
() => [...document.querySelectorAll('[data-testid="result-card"], article')].slice(0, 200).map(c => ({
  title: c.querySelector('h2, h3')?.innerText.trim() ?? null,
  href: c.querySelector('a[href]')?.href ?? null,
  meta: c.querySelector('time')?.getAttribute('datetime') ?? null,
  text: c.innerText.trim().slice(0, 300)
}))
```

Selectors are page-specific: inspect the snapshot first and adapt; prefer stable attributes
(`data-testid`, `aria-label`, `itemprop`) over generated class names.

## All links in the main content

```js
() => [...document.querySelectorAll('main a[href], article a[href]')]
  .map(a => ({ text: a.innerText.trim().slice(0, 120), href: a.href }))
  .filter((l, i, arr) => l.href.startsWith('http') && arr.findIndex(x => x.href === l.href) === i)
```

## Structured data already on the page

```js
() => [...document.querySelectorAll('script[type="application/ld+json"]')]
  .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
  .filter(Boolean)
```

JSON-LD often carries product, article, event or organization fields cleaner than the visible HTML.

## Infinite scroll

Loop from the agent side, not inside one long evaluate:
1. `browser_evaluate {function: "() => { window.scrollTo(0, document.body.scrollHeight); return document.querySelectorAll('article').length; }"}`
2. `browser_wait_for {time: 2}` or a text condition for the next batch.
3. Repeat until the count stops growing twice or reaches the cap; then extract once.

Better: open `browser_network_requests {static: false}` after the first scroll; if a JSON endpoint
with `page`/`cursor` serves the items, read it directly (public endpoints only) and stop scrolling.

## Page metadata for citations

```js
() => ({
  title: document.title,
  canonical: document.querySelector('link[rel=canonical]')?.href ?? location.href,
  published: document.querySelector('meta[property="article:published_time"]')?.content
          ?? document.querySelector('time[datetime]')?.getAttribute('datetime') ?? null,
  modified: document.querySelector('meta[property="article:modified_time"]')?.content ?? null,
  author: document.querySelector('meta[name=author]')?.content ?? null
})
```
