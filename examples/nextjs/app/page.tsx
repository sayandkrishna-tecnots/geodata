/**
 * A React Server Component. `countries()` runs at build time here, so the
 * 250-row table never reaches the browser -- only the rendered `<option>`s do.
 *
 * The three tiers of this page are the three ways the package is meant to be
 * used, in order of cost:
 *
 *   1. countries  -- RSC, from the root entry (~46 KB gz, and not even shipped)
 *   2. states     -- client, `await statesOf(iso2)`, one country's chunk
 *   3. cities     -- server route handler, because the table is 4.7 MB
 */

import { countries } from "geodata-js";

import AddressPicker from "./address-picker";

export default function Page() {
  const options = countries().map((c) => ({
    iso2: c.iso2,
    name: c.name,
    emoji: c.emoji,
    hasStates: c.has_states,
  }));

  return (
    <main>
      <h1>Cascading address selector</h1>
      <p>
        Country and subdivision resolve in the browser; cities come from a route
        handler, because shipping 152,970 of them to a client would cost 4.7 MB.
      </p>
      <AddressPicker countries={options} />
    </main>
  );
}
