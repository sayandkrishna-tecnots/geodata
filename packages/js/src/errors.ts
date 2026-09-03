/**
 * Errors the query API throws.
 *
 * `Ambiguous` is raised rather than picking a match arbitrarily: a silent wrong
 * answer in geographic data propagates into addresses and shipping, and the
 * dataset genuinely contains repeated names within one country.
 */

export class GeodataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
    // Restores the prototype chain when the package is consumed as compiled
    // ES5 by an older bundler, where `instanceof` otherwise silently fails.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** No record matched the lookup. */
export class NotFound extends GeodataError {}
export class CountryNotFound extends NotFound {}
export class StateNotFound extends NotFound {}
export class CityNotFound extends NotFound {}
export class LanguageNotFound extends NotFound {}

/** The lookup matched more than one record. */
export class Ambiguous extends GeodataError {}
