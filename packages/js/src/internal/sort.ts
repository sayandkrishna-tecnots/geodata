/**
 * Ordering, in one place so every entry point agrees.
 *
 * Deliberately not `localeCompare`: it is locale- and ICU-version-dependent, so
 * the same query would order differently on two machines, and it would diverge
 * from the Python API, which sorts by codepoint. Stable ordering across
 * languages is what makes the shared conformance suite meaningful.
 */
export function byName<T extends { name: string }>(a: T, b: T): number {
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}
