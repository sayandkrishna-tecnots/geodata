# Churn report: 2026.09 -> dev

Generated 2026-09-03. Review this before releasing (Decision 6).

- **from:** data/snapshots/2026.09
- **to:** data/canonical

## Threshold breaches

None. All deltas are within the churn budget.

## Summary

| entity | before | after | net | matched | added | gone | unmatched | renamed | id changed | re-parented |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| countries | 250 | 250 | +0 | 250 | 0 | 0 | 0 | 0 | 0 | 0 |
| states | 5,308 | 5,308 | +0 | 5,308 | 0 | 0 | 0 | 0 | 0 | 0 |
| cities | 152,970 | 152,970 | +0 | 152,970 | 0 | 0 | 0 | 0 | 0 | 0 |

**gone** = the name no longer appears anywhere in that country: real data leaving. **unmatched** = the name is still present but could not be paired one-to-one, which usually means upstream deduplicated or re-parented it. Only *gone* counts against the churn budget.

## countries

Match quality: `iso2` 250.

## states

Match quality: `iso3166_2` 5,300, `state_code` 8.

## cities

Match quality: `state+name` 152,621, `state+name+coords` 349.

