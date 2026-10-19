# Reference formats

## Citation keys

`<first author surname><year><first significant title word>`, lowercase ASCII, no punctuation:
`vaswani2017attention`, `leviathan2023fast`. Collision: append `a`, `b`.

## BibTeX-style entries

Published conference paper (with its arXiv preprint):

```bibtex
@inproceedings{vaswani2017attention,
  author    = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title     = {Attention Is All You Need},
  booktitle = {Advances in Neural Information Processing Systems 30 (NeurIPS 2017)},
  year      = {2017},
  eprint    = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url       = {https://arxiv.org/abs/1706.03762}
}
```

Preprint only:

```bibtex
@misc{surname2026word,
  author        = {Surname, Given and Other, Author},
  title         = {Title in Title Case},
  year          = {2026},
  eprint        = {2601.01234},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  note          = {Preprint, version v2 read on 2026-10-19},
  url           = {https://arxiv.org/abs/2601.01234v2}
}
```

Journal article:

```bibtex
@article{surname2025word,
  author  = {Surname, Given},
  title   = {Title},
  journal = {Journal Name},
  volume  = {12},
  number  = {3},
  pages   = {101--130},
  year    = {2025},
  doi     = {10.xxxx/xxxxx}
}
```

SSRN working paper: `@misc` with `howpublished = {SSRN Working Paper}`, `note = {SSRN id <n>}`,
`url = {https://papers.ssrn.com/sol3/papers.cfm?abstract_id=<n>}`.

Software or dataset: `@misc` with `version`, `howpublished = {GitHub repository}` or the archive
(Zenodo DOI preferred), and access date in `note`.

## Rules

- Take venue, volume, pages and year from Crossref or the publisher page, not from memory or a
  third-party export.
- Author names exactly as published (diacritics escaped or UTF-8 consistently); "and others" only
  if the brief allows truncation.
- Preprints are labelled as preprints; never invent a venue for one.
- Record which version you read (`v2`, or the published version) whenever numbers are cited.

## Numbered list in the synthesis

```
[1] Vaswani, A., et al. (2017). Attention Is All You Need. NeurIPS 2017. arXiv:1706.03762.
[2] Surname, G., & Other, A. (2026). Title. Preprint. arXiv:2601.01234v2.
```
