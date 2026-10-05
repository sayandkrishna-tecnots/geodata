# Churn report: 2026.09 -> v3.2-export.9

Generated 2026-10-05. Review this before releasing (Decision 6).

- **from:** data/snapshots/2026.09
- **to:** data/canonical

## Threshold breaches

None. All deltas are within the churn budget.

## Summary

| entity | before | after | net | matched | added | gone | unmatched | renamed | id changed | re-parented |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| countries | 250 | 250 | +0 | 250 | 0 | 0 | 0 | 0 | 0 | 0 |
| states | 5,308 | 5,308 | +0 | 5,308 | 0 | 0 | 0 | 0 | 0 | 0 |
| cities | 152,970 | 153,312 | +342 | 152,945 | 367 | 25 | 0 | 0 | 2 | 3 |

**gone** = the name no longer appears anywhere in that country: real data leaving. **unmatched** = the name is still present but could not be paired one-to-one, which usually means upstream deduplicated or re-parented it. Only *gone* counts against the churn budget.

## countries

Match quality: `iso2` 250.

Field-level changes on matched rows: `currency` 2.

## states

Match quality: `iso3166_2` 5,300, `state_code` 8.

## cities

Match quality: `state+name` 152,593, `state+name+coords` 349, `country+name+coords` 3.

**2 rows kept their identity but changed id.** This is the churn that silently corrupts foreign keys in already-seeded apps -- see the remap table and `geodata_migrate`.

### Added (367)

| country | count |
|---|---:|
| TW | 343 |
| AE | 13 |
| CU | 5 |
| DE | 3 |
| GB | 2 |
| IN | 1 |

<details><summary>first 25 rows</summary>

- `163965` Al Barsha (AE)
- `163966` Naif (AE)
- `163967` Al Awir (AE)
- `163968` Dubai Marina (AE)
- `163969` Jebel Ali (AE)
- `163970` Deira (AE)
- `163971` Bur Dubai (AE)
- `163972` Business Bay (AE)
- `163973` Jumeirah (AE)
- `163974` Yas Island (AE)
- `163975` Saadiyat Island (AE)
- `163976` Al Reem Island (AE)
- `163977` Al Raha (AE)
- `163978` Playa (CU)
- `163979` Plaza de la Revolución (CU)
- `163980` Marianao (CU)
- `163981` La Lisa (CU)
- `163982` Cotorro (CU)
- `163984` Bensersiel (DE)
- `163985` Burhave (DE)
- `163983` Au (DE)
- `163986` Uxbridge (GB)
- `163987` Twickenham (GB)
- `147670` Ahilyanagar (IN)
- `164022` Sanxing Township (TW)

</details>

### Gone (name absent from the country) (25)

| country | count |
|---|---:|
| US | 24 |
| IN | 1 |

<details><summary>first 25 rows</summary>

- `147670` Ahmednagar (IN)
- `111143` Aleutians East Borough (US)
- `111144` Aleutians West Census Area (US)
- `111306` Anchorage Municipality (US)
- `112284` Bethel Census Area (US)
- `112813` Bristol Bay Borough (US)
- `114045` City and Borough of Wrangell (US)
- `115235` Denali Borough (US)
- `115341` Dillingham Census Area (US)
- `116291` Fairbanks North Star Borough (US)
- `117844` Haines Borough (US)
- `118632` Hoonah-Angoon Census Area (US)
- `119441` Kenai Peninsula Borough (US)
- `119524` Ketchikan Gateway Borough (US)
- `119699` Kodiak Island Borough (US)
- `120003` Lake and Peninsula Borough (US)
- `121399` Matanuska-Susitna Borough (US)
- `122935` Nome Census Area (US)
- `123107` North Slope Borough (US)
- `123173` Northwest Arctic Borough (US)
- `124110` Petersburg Borough (US)
- `126471` Sitka City and Borough (US)
- `126766` Southeast Fairbanks Census Area (US)
- `128084` Valdez-Cordova Census Area (US)
- `129731` Yukon-Koyukuk Census Area (US)

</details>

### Re-parented (3)

| country | count |
|---|---:|
| TW | 2 |
| MX | 1 |

A re-parented city keeps its identity but answers a different `state_id`. Queries that filter by the old state return nothing -- this is the France/INSEE breaking change.

