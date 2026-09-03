# data/curated

Hand-maintained reference tables that are *derived from upstream documentation*
rather than from upstream data files. Unlike `data/overrides/`, these do not
change any upstream value -- they add relationships upstream documents in prose
but does not encode in JSON.

## multi_level_territories.ndjson

The 21 territories that ISO 3166 lists at both levels: as a country
(ISO 3166-1) and as a subdivision of another country (ISO 3166-2).

Transcribed from upstream `MULTI_LEVEL_TERRITORIES.md` at the tag recorded in
`data/SOURCE.lock`. Produces the `also_subdivision_of` field on countries
(Decision 3). `state_id` values are validated against the canonical states file
at build time -- a stale entry fails the build rather than being silently dropped.

Source: https://github.com/dr5hn/countries-states-cities-database/blob/v3.2-export.7/MULTI_LEVEL_TERRITORIES.md

Note the deliberate exclusions upstream documents as "known gaps": Greenland
(DK), Faroe Islands (DK), Aruba/Curacao/Sint Maarten (NL) and others are modeled
only as countries, not as subdivisions. They are absent here for that reason,
not by oversight.
