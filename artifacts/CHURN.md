# Churn report: 2026.09 -> v5.0.0-export.1

Generated 2026-10-26. Review this before releasing (Decision 6).

- **from:** data/snapshots/2026.09
- **to:** data/canonical

## Threshold breaches -- sign-off required

These exceed the churn budget (2.0% net removal per entity, 10.0% per country). Releasing anyway requires `--accept-churn` with a written justification recorded in the CHANGELOG.

- **cities**: 6,075 rows disappeared entirely (4.0% of 152,970, limit 2.0%)
- **cities/RO**: 2,886 rows disappeared entirely (50% of the rows that moved for this country)
- **cities/JP**: 412 rows disappeared entirely (96% of the rows that moved for this country)
- **cities/RU**: 318 rows disappeared entirely (79% of the rows that moved for this country)
- **cities/TH**: 278 rows disappeared entirely (84% of the rows that moved for this country)
- **cities/VN**: 243 rows disappeared entirely (51% of the rows that moved for this country)
- **cities/AR**: 231 rows disappeared entirely (64% of the rows that moved for this country)
- **cities/IN**: 188 rows disappeared entirely (36% of the rows that moved for this country)
- **cities/HU**: 165 rows disappeared entirely (100% of the rows that moved for this country)
- **cities/ID**: 148 rows disappeared entirely (52% of the rows that moved for this country)
- **cities/GB**: 140 rows disappeared entirely (93% of the rows that moved for this country)
- **cities/UA**: 126 rows disappeared entirely (47% of the rows that moved for this country)
- **cities/CH**: 122 rows disappeared entirely (100% of the rows that moved for this country)
- **cities/FR**: 109 rows disappeared entirely (96% of the rows that moved for this country)

## Summary

| entity | before | after | net | matched | added | gone | unmatched | renamed | id changed | re-parented |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| countries | 250 | 250 | +0 | 250 | 0 | 0 | 0 | 0 | 0 | 0 |
| states | 5,308 | 5,328 | +20 | 5,303 | 25 | 5 | 0 | 16 | 11 | 0 |
| cities | 152,970 | 152,021 | -949 | 145,684 | 6,337 | 6,075 | 1,211 | 9 | 1,232 | 7,868 |

**gone** = the name no longer appears anywhere in that country: real data leaving. **unmatched** = the name is still present but could not be paired one-to-one, which usually means upstream deduplicated or re-parented it. Only *gone* counts against the churn budget.

## countries

Match quality: `iso2` 250.

Field-level changes on matched rows: `currency` 5, `capital` 1.

## states

Match quality: `iso3166_2` 5,286, `state_code` 15, `name` 2.

**11 rows kept their identity but changed id.** This is the churn that silently corrupts foreign keys in already-seeded apps -- see the remap table and `geodata_migrate`.

### Added (25)

| country | count |
|---|---:|
| MT | 6 |
| TN | 5 |
| IT | 4 |
| SH | 3 |
| ET | 2 |
| PH | 2 |
| GR | 1 |
| HR | 1 |
| IQ | 1 |

<details><summary>first 25 rows</summary>

- `5827` Central Ethiopia (ET)
- `5828` South Ethiopia (ET)
- `5840` Mount Athos (GR)
- `5834` City of Zagreb (HR)
- `5841` Halabja (IQ)
- `5830` Gallura Nord-Est Sardegna (IT)
- `5831` Ogliastra (IT)
- `5832` Medio Campidano (IT)
- `5833` Sulcis Iglesiente (IT)
- `5842` Northern Region (MT)
- `5843` Eastern Region (MT)
- `5844` Western Region (MT)
- `5845` Port Region (MT)
- `5846` Southern Region (MT)
- `5847` Gozo Region (MT)
- `5829` Special Geographic Area (PH)
- `5853` Negros Island Region (PH)
- `5837` Ascension (SH)
- `5838` Saint Helena (SH)
- `5839` Tristan da Cunha (SH)
- `5848` District 1 (TN)
- `5849` District 2 (TN)
- `5850` District 3 (TN)
- `5851` District 4 (TN)
- `5852` District 5 (TN)

</details>

### Gone (name absent from the country) (5)

| country | count |
|---|---:|
| TT | 2 |
| ET | 1 |
| GR | 1 |
| IT | 1 |

<details><summary>first 25 rows</summary>

- `1` Southern Nations, Nationalities, and Peoples (ET)
- `2116` Achaea (GR)
- `1730` South Sardinia (IT)
- `3353` Western Tobago (TT)
- `3355` Eastern Tobago (TT)

</details>

### Renamed (16)

| id | before | after | country |
|---|---|---|---|
| 216 | Cuanza | Cuanza Sul | AO |
| 1530 | Denmark | Capital Region of Denmark | DK |
| 4910 | El M'ghair | Timimoun | DZ |
| 4908 | El Menia | Bordj Baji Mokhtar | DZ |
| 4909 | Bordj Baji Mokhtar | Béni Abbès | DZ |
| 4913 | Béni Abbès | In Salah | DZ |
| 4914 | Timimoun | In Guezzam | DZ |
| 4905 | In Salah | El M'ghair | DZ |
| 4906 | In Guezzam | El Menia | DZ |
| 5759 | Lääne-Harju | Lääneranna | EE |
| 5758 | Lääneranna | Lääne-Harju | EE |
| 5773 | Põhja-Pärnu | Põhja-Pärnumaa | EE |
| 5333 | Estremadura | Extremadura | ES |
| 5575 | Hörðarsveit | Hörgársveit | IS |
| 2046 | Venezuela | Federal Dependencies | VE |
| 3798 | Thừa Thiên-Huế | Huế | VN |

## cities

Match quality: `state+name` 134,494, `country+name+coords` 7,733, `state+name+coords` 3,342, `country+name` 100, `name_tokens+coords` 8, `id+name` 6, `name_tokens` 1.

**1,232 rows kept their identity but changed id.** This is the churn that silently corrupts foreign keys in already-seeded apps -- see the remap table and `geodata_migrate`.

### Added (6,337)

| country | count |
|---|---:|
| RO | 2,888 |
| IT | 400 |
| TW | 343 |
| IN | 330 |
| VN | 238 |
| UA | 140 |
| ID | 138 |
| AR | 128 |
| VE | 123 |
| RU | 86 |
| MX | 84 |
| NO | 65 |
| ZA | 60 |
| PE | 57 |
| TH | 52 |
| EG | 47 |
| CN | 42 |
| MM | 42 |
| AF | 38 |
| ET | 38 |
| _118 more_ | 998 |

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
- `164336` Ḩattā (AE)
- `163974` Yas Island (AE)
- `163975` Saadiyat Island (AE)
- `163976` Al Reem Island (AE)
- `163977` Al Raha (AE)
- `164357` Mīray (AF)
- `164361` Qarah Bāgh (AF)
- `164363` Rāmak (AF)
- `164371` ‘Alāqahdārī Gēlān (AF)
- `164349` Jawand (AF)
- `164362` Qādis (AF)
- `165918` Bala Murghab (AF)
- `164344` Bulōlah (AF)
- `164339` Khān Neshīn (AF)
- `164358` Mūsá Qal‘ah (AF)
- `164343` Banū (AF)

</details>

### Gone (name absent from the country) (6,075)

| country | count |
|---|---:|
| RO | 2,886 |
| JP | 412 |
| RU | 318 |
| TH | 278 |
| VN | 243 |
| AR | 231 |
| IN | 188 |
| HU | 165 |
| ID | 148 |
| GB | 140 |
| UA | 126 |
| CH | 122 |
| FR | 109 |
| CZ | 79 |
| MX | 70 |
| ES | 63 |
| PH | 62 |
| PE | 60 |
| US | 49 |
| IT | 34 |
| _71 more_ | 292 |

<details><summary>first 25 rows</summary>

- `58` Bāsawul (AF)
- `136` Āqchah (AF)
- `505` Rrind (AM)
- `477` Musalerr (AM)
- `387` Gavarr (AM)
- `386` Garrni (AM)
- `442` Lerrnanist (AM)
- `500` Prroshyan (AM)
- `583` Zarr (AM)
- `633` Soio (AO)
- `844` Departamento de Calingasta (AR)
- `851` Departamento de Capital (AR)
- `856` Departamento de Caucete (AR)
- `859` Departamento de Chimbas (AR)
- `907` Departamento de Iglesia (AR)
- `915` Departamento de Jáchal (AR)
- `952` Departamento de Nueve de Julio (AR)
- `964` Departamento de Rawson (AR)
- `966` Departamento de Rivadavia (AR)
- `998` Departamento de San Martín (AR)
- `1005` Departamento de Santa Lucía (AR)
- `1013` Departamento de Sarmiento (AR)
- `1028` Departamento de Ullúm (AR)
- `1036` Departamento de Zonda (AR)
- `1339` Pocito (AR)

</details>

### Unmatched (name still present) (1,211)

| country | count |
|---|---:|
| PH | 940 |
| ES | 47 |
| UA | 33 |
| MX | 27 |
| JP | 25 |
| PT | 23 |
| RU | 22 |
| TR | 18 |
| CN | 13 |
| AR | 11 |
| DZ | 8 |
| GR | 6 |
| US | 6 |
| IN | 5 |
| GB | 3 |
| KE | 3 |
| RO | 3 |
| TH | 3 |
| VN | 3 |
| IT | 2 |
| _8 more_ | 10 |

<details><summary>first 25 rows</summary>

- `926` Departamento de Lavalle (AR)
- `983` Departamento de San Carlos (AR)
- `1440` San Martín (AR)
- `1102` General Enrique Mosconi (AR)
- `910` Departamento de Independencia (AR)
- `154334` Castelli (AR)
- `154389` Malvinas Argentinas (AR)
- `154400` Nueve de Julio (AR)
- `154415` Rivadavia (AR)
- `154292` Saavedra (AR)
- `154294` San Nicolás (AR)
- `8150` Qobustan (AZ)
- `19784` Kunshan (CN)
- `19941` Nanjing (CN)
- `19949` Nantong (CN)
- `20163` Taizhou (CN)
- `20239` Wuxi (CN)
- `20349` Yangzhou (CN)
- `158060` Yancheng (CN)
- `157376` Suzhou (CN)
- `19304` Baise (CN)
- `19571` Guilin (CN)
- `159577` Changzhou (CN)
- `157434` Zhenjiang (CN)
- `157509` Chengqu (CN)

</details>

### Renamed (9)

| id | before | after | country |
|---|---|---|---|
| 151157 | Porriño O | O Porriño | ES |
| 152914 | Pobla Sa | Sa Pobla | ES |
| 151465 | Palacios y Villafranca Los | Los Palacios y Villafranca | ES |
| 151042 | Laracha A | A Laracha | ES |
| 151076 | Incio O | O Incio | ES |
| 36147 | Pereiro de Aguiar O | O Pereiro de Aguiar | ES |
| 151361 | Barrios Los | Los Barrios | ES |
| 80920 | Puerto Supe | Supe Puerto | PE |
| 130426 | Huyện Tây Sơn | Huyện Sơn Tây | VN |

### Re-parented (7,868)

| country | count |
|---|---:|
| PH | 2,652 |
| GB | 1,343 |
| CZ | 1,207 |
| BE | 524 |
| IT | 279 |
| IE | 212 |
| MX | 192 |
| PT | 192 |
| GR | 131 |
| UA | 128 |
| EE | 120 |
| MA | 99 |
| FR | 93 |
| ES | 87 |
| JP | 66 |

A re-parented city keeps its identity but answers a different `state_id`. Queries that filter by the old state return nothing -- this is the France/INSEE breaking change.

