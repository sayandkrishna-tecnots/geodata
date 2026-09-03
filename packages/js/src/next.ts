/**
 * A ready-made server endpoint for city and subdivision lookup.
 *
 * ```ts
 * // app/api/geo/route.ts
 * import { createGeoHandler } from "geodata-js/next";
 * export const GET = createGeoHandler();
 * ```
 *
 * This is the answer to "how does a client component search 152,970 cities?".
 * The data stays on the server; the browser sends a query and receives at most
 * `limit` rows. Nothing about it is Next-specific beyond the name -- the
 * handler takes a `Request` and returns a `Response`, so it works unchanged in
 * Remix, Hono, Bun.serve, Deno.serve, or any Web-standard runtime.
 *
 * It imports `geodata-js/cities`, so the module that calls it must be
 * server-only. In Next.js, add `serverExternalPackages: ["geodata-js"]` to
 * `next.config.js` to keep 4.7 MB out of every serverless function trace.
 *
 * ## Endpoints
 *
 *   GET ?q=lagos&country=NG&limit=10   city search
 *   GET ?country=NG                    that country's top-level subdivisions
 *   GET ?country=NG&state=NG-LA        that subdivision's cities
 *   GET (no params)                    all 250 countries, minimal fields
 */

import { citiesOf, searchCities } from "./cities.js";
import { countries, getCountry } from "./index.js";
import { NotFound } from "./errors.js";
import { rootStates, statesOf } from "./states.js";
import { DATASET_VERSION, VERSION } from "./generated/version.js";

export interface GeoHandlerOptions {
  /** Hard ceiling on rows per response. Default 50. */
  maxLimit?: number;
  /**
   * `Cache-Control` for successful responses. The dataset is immutable for the
   * lifetime of an installed version, so the default caches hard and lets a
   * CDN serve stale copies indefinitely while it revalidates.
   */
  cacheControl?: string;
  /** Restrict to these ISO 3166-1 alpha-2 codes. Default: all of them. */
  onlyCountries?: string[];
}

function json(body: unknown, status: number, cacheControl?: string): Response {
  const headers: Record<string, string> = { "content-type": "application/json; charset=utf-8" };
  if (cacheControl && status < 400) headers["cache-control"] = cacheControl;
  return new Response(JSON.stringify(body), { status, headers });
}

/**
 * Build a `(request: Request) => Response` over the dataset.
 *
 * Errors are deliberately mapped to status codes rather than propagated: a
 * `CountryNotFound` from a user-supplied query string is a 404, not a 500, and
 * an unrecognised parameter should not leak a stack trace to the client.
 */
export function createGeoHandler(options: GeoHandlerOptions = {}) {
  const maxLimit = options.maxLimit ?? 50;
  const cacheControl =
    options.cacheControl ?? "public, max-age=3600, stale-while-revalidate=86400, immutable";
  const allowed = options.onlyCountries
    ? new Set(options.onlyCountries.map((c) => c.toUpperCase()))
    : undefined;

  return function handler(request: Request): Response {
    const params = new URL(request.url).searchParams;
    const q = params.get("q")?.trim() ?? "";
    const countryParam = params.get("country")?.trim() ?? "";
    const stateParam = params.get("state")?.trim() ?? "";
    const rawLimit = Number(params.get("limit"));
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, maxLimit) : 25;

    try {
      if (!countryParam && !q) {
        const rows = countries()
          .filter((c) => !allowed || allowed.has(c.iso2))
          .map((c) => ({
            iso2: c.iso2,
            name: c.name,
            emoji: c.emoji,
            phone_code: c.phone_code,
            has_states: c.has_states,
          }));
        return json({ version: VERSION, dataset: DATASET_VERSION, countries: rows }, 200, cacheControl);
      }

      const country = countryParam ? getCountry(countryParam) : undefined;
      if (country && allowed && !allowed.has(country.iso2)) {
        return json({ error: `country ${country.iso2} is not served by this endpoint` }, 403);
      }

      if (q) {
        const rows = searchCities(q, { country, limit });
        return json({ query: q, cities: rows }, 200, cacheControl);
      }

      // A country with no state parameter: the dropdown's first tier.
      if (country && !stateParam) {
        return json(
          { country: country.iso2, states: rootStates(country), all_depths: statesOf(country).length },
          200,
          cacheControl,
        );
      }

      // Both: the dropdown's second tier.
      return json(
        { country: country!.iso2, state: stateParam, cities: citiesOf(country!, { state: stateParam, limit }) },
        200,
        cacheControl,
      );
    } catch (error) {
      if (error instanceof NotFound) return json({ error: error.message }, 404);
      // Ambiguous, and anything else the query surface raises on bad input.
      return json({ error: error instanceof Error ? error.message : "bad request" }, 400);
    }
  };
}

export default createGeoHandler;
