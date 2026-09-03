/**
 * The server half: city lookup for the client component.
 *
 * `createGeoHandler` is a plain `(Request) => Response`, so this file is four
 * lines. It imports `geodata-js/cities` internally, which is why it may only
 * ever be reached from the server -- and why `next.config.mjs` sets
 * `serverExternalPackages`, keeping the 4.7 MB table out of the deployed
 * function trace rather than inlined into it.
 *
 *   GET /api/cities?country=NG&state=NG-LA&limit=50   cities of a subdivision
 *   GET /api/cities?q=lag&country=NG                  prefix search
 */

import { createGeoHandler } from "geodata-js/next";

export const GET = createGeoHandler({ maxLimit: 100 });

// Deliberately *not* `force-static`: this handler answers from the query
// string, and a statically evaluated route handler has no query string to read.
// The dataset is immutable for the lifetime of an installed version, so
// `createGeoHandler` sets a long `Cache-Control` instead and lets the CDN do
// the caching -- same benefit, without breaking the parameters.
export const dynamic = "force-dynamic";
