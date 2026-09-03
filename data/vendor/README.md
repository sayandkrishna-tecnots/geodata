# data/vendor

Committed input data that does **not** come from the pinned upstream export.

`scripts/fetch.py` only knows how to download `dr5hn/countries-states-cities-database`.
Anything else a build needs lives here, in the repo, under review — never fetched
at build time. That keeps the build reproducible: `make refresh` on a machine with
no network still produces byte-identical canonical output for these tables.

| file | rows | what it is |
|---|---|---|
| `languages.json` | 420 | ISO 639 language codes and English names |

## languages.json

`[{"code": "aa", "name": "Afar"}, ...]`, sorted by code. 184 two-letter codes
(ISO 639-1) and 236 three-letter codes (ISO 639-2/T), no duplicates.

It exists for one structural reason: the `translations.*.ndjson` artifacts are
keyed by BCP-47 tags (`pt-BR`, `zh-CN`, `fa`, …) and until now nothing in the
repo said what those tags mean or whether they were even well-formed. Validation
check 9 now resolves every translation tag's primary subtag against this table,
so a refresh that introduces an unknown locale fails the gate instead of shipping
a key no consumer can label.

Corrections go through `data/overrides/languages.patch.ndjson` like any other
table — same `_reason` / `_source` / `_review` requirement. Do not hand-edit this
file for a fix you cannot cite.
