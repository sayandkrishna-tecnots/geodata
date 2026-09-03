/**
 * State queries, expressed over a plain `State[]`.
 *
 * Parameterised on the rows for the same reason as `cityOps`: the async root
 * entry works from one country's chunk and `geodata-js/states` works from all
 * 5,308, and both must resolve a subdivision identically.
 *
 * Callers always pass rows already scoped to one country, so lookups here do
 * not re-check `country_iso2` -- the country is carried separately only so
 * error messages and `iso3166_2` qualification can name it.
 */

import { Ambiguous, StateNotFound } from "../errors.js";
import type { Country, State, StateNode } from "../generated/types.js";
import { normalizeName } from "../normalize.js";
import { byName } from "./sort.js";

/** Explicit-tier lookup, when a bare string would be ambiguous about which tier it means. */
export interface StateQuery {
  iso3166_2?: string;
  state_code?: string;
  name?: string;
}

/** Anything `getState`/`statesOf` accepts as a subdivision reference. */
export type StateRef = State | string | number | StateQuery;

/** Filters accepted by `statesOf`. */
export interface StateFilter {
  /**
   * Position in the parent chain, computed by the build and authoritative.
   * `depth: 1` is the top level -- GB gives England, Northern Ireland,
   * Scotland, Wales. This is what a first-tier dropdown wants.
   */
  depth?: number;
  /**
   * Upstream's semantic administrative level. **Advisory only**: it disagrees
   * with the actual tree for 996 states (Belgian provinces are level 1 sitting
   * under level 1 regions), so prefer `depth`.
   */
  level?: number;
  /** Restrict to the direct children of one state. */
  parent?: StateRef;
  /** `"council area"`, `"province"`, ... */
  type?: string;
}

function isRow(key: unknown): key is State {
  return typeof key === "object" && key !== null && "id" in key && "country_iso2" in key;
}

export function filterStates(country: Country, rows: State[], filter: StateFilter = {}): State[] {
  let out = rows;
  if (filter.parent !== undefined) {
    const parent = isRow(filter.parent)
      ? filter.parent
      : lookupState(country, rows, filter.parent);
    out = out.filter((s) => s.parent_id === parent.id);
  }
  if (filter.depth !== undefined) out = out.filter((s) => s.depth === filter.depth);
  if (filter.level !== undefined) out = out.filter((s) => s.level === filter.level);
  if (filter.type !== undefined) out = out.filter((s) => s.type === filter.type);
  return out.slice().sort(byName);
}

function only(bucket: State[], describe: () => string): State | undefined {
  if (bucket.length === 0) return undefined;
  if (bucket.length > 1) {
    const names = bucket.map((s) => s.iso3166_2 ?? s.name).sort().join(", ");
    throw new Ambiguous(`${describe()} matches ${bucket.length} states: ${names}`);
  }
  return bucket[0];
}

const byIsoCode = (rows: State[], code: string) =>
  rows.filter((s) => (s.iso3166_2 ?? "").toUpperCase() === code);
const byStateCode = (rows: State[], code: string) =>
  rows.filter((s) => (s.state_code ?? "").toUpperCase() === code);
const byNormalizedName = (rows: State[], needle: string) =>
  rows.filter((s) => s.normalized_name === needle);

/**
 * Resolve a subdivision within one country.
 *
 * Tiers run most-specific first, in the priority order of the stable-key
 * strategy: the full ISO 3166-2 code, the same code qualified with the country
 * (`"BIR"` -> `"GB-BIR"`), the bare `state_code`, then the normalized name.
 *
 * Throws {@link Ambiguous} rather than guessing when a name matches twice.
 */
export function lookupState(country: Country, rows: State[], key: StateRef): State {
  const iso2 = country.iso2;

  if (isRow(key)) return key;

  if (typeof key === "object") {
    if (key.iso3166_2 !== undefined) {
      const text = key.iso3166_2.toUpperCase();
      const hit =
        byIsoCode(rows, text)[0] ?? byIsoCode(rows, `${iso2}-${text}`.toUpperCase())[0];
      if (!hit) {
        throw new StateNotFound(
          `no state with iso3166_2 ${JSON.stringify(key.iso3166_2)} in ${iso2}`,
        );
      }
      return hit;
    }
    if (key.state_code !== undefined) {
      const code = key.state_code;
      const hit = only(byStateCode(rows, code.toUpperCase()), () =>
        `state_code ${JSON.stringify(code)} in ${iso2}`,
      );
      if (!hit) {
        throw new StateNotFound(`no state with state_code ${JSON.stringify(code)} in ${iso2}`);
      }
      return hit;
    }
    if (key.name !== undefined) {
      const name = key.name;
      const hit = only(byNormalizedName(rows, normalizeName(name)), () =>
        `name ${JSON.stringify(name)} in ${iso2}`,
      );
      if (!hit) throw new StateNotFound(`no state named ${JSON.stringify(name)} in ${iso2}`);
      return hit;
    }
    throw new StateNotFound("give an iso3166_2, state_code or name");
  }

  if (typeof key === "number") {
    const hit = rows.find((s) => s.id === key);
    if (!hit) throw new StateNotFound(`no state ${key} in ${iso2}`);
    return hit;
  }

  const text = key.trim();
  const upper = text.toUpperCase();
  const describe = () => `${JSON.stringify(key)} in ${iso2}`;
  const hit =
    byIsoCode(rows, upper)[0] ??
    byIsoCode(rows, `${iso2}-${upper}`)[0] ??
    only(byStateCode(rows, upper), describe) ??
    only(byNormalizedName(rows, normalizeName(text)), describe);
  if (!hit) throw new StateNotFound(`no state ${JSON.stringify(key)} in ${iso2}`);
  return hit;
}

/** The direct children of a state, sorted by name. */
export function childrenOf(rows: State[], state: State | number): State[] {
  const id = typeof state === "number" ? state : state.id;
  return rows.filter((s) => s.parent_id === id).sort(byName);
}

/** Subdivisions as a forest, roots (depth 1) first. */
export function buildTree(country: Country, rows: State[]): StateNode[] {
  const byParent = new Map<number, State[]>();
  for (const s of rows) {
    if (s.parent_id === null) continue;
    const bucket = byParent.get(s.parent_id);
    if (bucket) bucket.push(s);
    else byParent.set(s.parent_id, [s]);
  }
  const build = (state: State): StateNode => ({
    state,
    children: (byParent.get(state.id) ?? []).slice().sort(byName).map(build),
  });
  return filterStates(country, rows, { depth: 1 }).map(build);
}

/** Depth-first walk of a node and all its descendants. */
export function* walk(node: StateNode): Generator<State> {
  yield node.state;
  for (const child of node.children) yield* walk(child);
}
