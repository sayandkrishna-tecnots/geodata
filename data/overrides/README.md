# data/overrides

The escape hatch that stops us forking 35 MB of upstream data (Decision 4).

Each line is a JSON object applied to the canonical records *after* ingest and
*before* validation. Keep this file tiny: if it grows past a few dozen lines,
the right move is a PR upstream, not more local patching.

## Format

```jsonc
{
  "_op": "patch",              // patch | add | remove
  "_match": {"id": 1160},      // or {"iso2": "XK"} etc. -- must match exactly one record
  "parent_id": null,           // every other key is the field to set
  "_reason": "why upstream is wrong, in a sentence",
  "_source": "https://...",    // evidence
  "_review": "2026-09-03"      // date a human signed off
}
```

`_reason`, `_source` and `_review` are mandatory and enforced by the loader.

## Rules

1. Every entry needs a reason and a source URL. No exceptions.
2. `_match` must resolve to exactly one record -- zero or many is a build error,
   which is how a stale override announces itself after an upstream refresh.
3. `scripts/validate.py --report-retired-overrides` lists any override upstream
   has since adopted, so it can be deleted.
4. Prefer fixing upstream. An override is a stopgap with a date on it.
