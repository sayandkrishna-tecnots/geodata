#!/usr/bin/env bash
#
# Install the packed tarball into a clean directory and use it the way a
# consumer would.
#
# This is the only check that proves the *published artifact* works. The test
# suite imports `src/`, and `npm pack --dry-run` only lists filenames -- neither
# would notice a broken exports map, a missing data file, or the .gitignore
# fallback that once produced a tarball containing three licences and no code.
#
# Covers ESM, CJS, the subpath exports, and a TypeScript consumer under
# `moduleResolution: node16`, which is where dual-package type errors surface.
set -euo pipefail

pkg_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> packing"
cd "$pkg_dir"
tarball="$work/$(npm pack --silent --pack-destination "$work")"

echo "==> installing into a clean tree ($work)"
cd "$work"
npm init -y >/dev/null
npm install --silent --no-audit --no-fund "$tarball"

expect() { # expect <label> <actual> <wanted>
  if [ "$2" = "$3" ]; then
    echo "    ok   $1 = $2"
  else
    echo "    FAIL $1: got '$2', want '$3'" >&2
    exit 1
  fi
}

echo "==> ESM"
cat > esm.mjs <<'JS'
import { getCountry, countries, COUNTS, DATASET_VERSION, statesOf } from "geodata-js";
import { statesOf as syncStates, subdivisionTwin } from "geodata-js/states";
import { citiesOf, searchCities } from "geodata-js/cities";
import { localizedName } from "geodata-js/translations";
import { normalizeName } from "geodata-js/normalize";
import { states as ngStates } from "geodata-js/country/NG";

const out = {
  dataset: DATASET_VERSION,
  countries: countries().length,
  counts: `${COUNTS.countries}/${COUNTS.states}/${COUNTS.cities}`,
  nigeria: getCountry("NG").name,
  gbStates: syncStates("GB").length,
  gbRoots: syncStates("GB", { depth: 1 }).length,
  twin: subdivisionTwin("MQ").iso3166_2,
  lagos: citiesOf("NG", { state: "NG-LA" }).length > 0,
  search: searchCities("sao paulo", { country: "BR", limit: 1 })[0].name,
  german: localizedName(getCountry("DE"), "fr"),
  fold: normalizeName("Saint-Étienne"),
  chunk: ngStates.length,
  lazy: (await statesOf("GB")).length,
};
console.log(JSON.stringify(out));
JS
esm="$(node esm.mjs)"
expect "esm dataset"   "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).dataset')" "2026.09"
expect "esm counts"    "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).counts')" "250/5308/152970"
expect "esm gb states" "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).gbStates')" "221"
expect "esm twin"      "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).twin')" "FR-972"
expect "esm search"    "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).search')" "São Paulo"
expect "esm translate" "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).german')" "Allemagne"
expect "esm fold"      "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).fold')" "saint etienne"
expect "esm lazy"      "$(echo "$esm" | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).lazy')" "221"

echo "==> CJS"
cat > cjs.cjs <<'JS'
const { getCountry, COUNTS } = require("geodata-js");
const { statesOf } = require("geodata-js/states");
const { citiesOf } = require("geodata-js/cities");
const { localizedName } = require("geodata-js/translations");
if (getCountry("NG").name !== "Nigeria") throw new Error("cjs: country lookup");
if (statesOf("GB").length !== 221) throw new Error("cjs: states");
if (citiesOf("NG", { state: "NG-LA" }).length === 0) throw new Error("cjs: cities");
if (localizedName(getCountry("DE"), "ja") !== "ドイツ") throw new Error("cjs: translations");
if (COUNTS.cities !== 152970) throw new Error("cjs: counts");
// The async surface must work here too -- CJS reaches the chunks through
// require() interop rather than a real dynamic import.
require("geodata-js").statesOf("NG").then((s) => {
  if (s.length === 0) throw new Error("cjs: async statesOf");
  console.log("    ok   cjs esm-interop, sync subpaths, async chunks");
});
JS
node cjs.cjs

echo "==> TypeScript (moduleResolution node16, both module systems)"
npm install --silent --no-audit --no-fund --save-dev typescript@5 >/dev/null
cat > consumer.ts <<'TS'
import { getCountry, type Country } from "geodata-js";
import { statesOf } from "geodata-js/states";
import type { State } from "geodata-js/states";
const c: Country = getCountry("NG");
const s: State[] = statesOf(c, { depth: 1 });
export const check: string = `${c.iso2}:${s.length}`;
TS
cat > consumer.cts <<'TS'
import { getCountry } from "geodata-js";
import { citiesOf } from "geodata-js/cities";
export const check: number = citiesOf(getCountry("NG")).length;
TS
cat > tsconfig.json <<'JSON'
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "node16",
    "moduleResolution": "node16",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": []
  },
  "files": ["consumer.ts", "consumer.cts"]
}
JSON
# ./node_modules/.bin, not npx: npx will happily fall back to a globally
# installed tsc, and a pre-4.7 one ignores "exports" entirely -- it resolves via
# "main", finds no sibling .d.ts, and reports TS7016 for a package whose types
# are in fact fine. That failure says nothing about this package.
./node_modules/.bin/tsc -p tsconfig.json
echo "    ok   type-checks from both ESM and CJS"

echo
echo "smoke passed: $(basename "$tarball")"
