/**
 * Loading a generated per-country chunk, and surviving module-format interop.
 *
 * Shared by the root entry (which loads subdivisions) and `geodata-js/lazy`
 * (which loads cities), so the two cannot disagree about how a chunk is
 * unwrapped.
 */

/**
 * Unwrap the ESM/CJS interop layer.
 *
 * Under native ESM the namespace already carries the named exports; under
 * CommonJS -- and under bundlers that wrap a CJS module in a synthetic
 * namespace -- they are only reachable through `default`. Every generated
 * module exports the same object both ways, so preferring `default` when it is
 * present is correct in both cases rather than a CJS-only patch.
 */
export function unwrap<T>(mod: unknown): T {
  return ((mod as { default?: T }).default ?? mod) as T;
}

export function chunkFor<T>(
  table: Record<string, () => Promise<unknown>>,
  iso2: string,
  what: string,
): Promise<T> {
  const load = table[iso2];
  /* c8 ignore next -- unreachable: a test asserts every iso2 in the country
     table has an entry in all three maps. Kept so a broken build fails loudly
     rather than throwing `undefined is not a function`. */
  if (!load) throw new Error(`no ${what} chunk generated for ${iso2}`);
  return load().then(unwrap<T>);
}

