"use client";

/**
 * The client half.
 *
 * Note what is imported: only the *root* entry, and only its async functions.
 * `await statesOf("NG")` dynamic-imports Nigeria's chunk -- 17 KB gzipped --
 * so the bundle carries no subdivision data until a country is picked, and
 * never carries the 336 KB whole-states table.
 *
 * Cities deliberately do *not* come from the package here. Importing
 * `geodata-js/cities` in a client component resolves to the browser stub and
 * throws, by design; the search box below calls `/api/cities` instead.
 */

import { useEffect, useState, useTransition } from "react";
import { statesOf, type State } from "geodata-js";

interface CountryOption {
  iso2: string;
  name: string;
  emoji: string | null;
  hasStates: boolean;
}

interface CityOption {
  id: number;
  name: string;
}

export default function AddressPicker({ countries }: { countries: CountryOption[] }) {
  const [country, setCountry] = useState("");
  const [states, setStates] = useState<State[]>([]);
  const [state, setState] = useState("");
  const [cities, setCities] = useState<CityOption[]>([]);
  const [loading, startTransition] = useTransition();

  useEffect(() => {
    if (!country) {
      setStates([]);
      return;
    }
    let live = true;
    // `{ depth: 1 }` is what a first-tier dropdown wants: the UK has 221
    // subdivisions across two levels, and only four belong at this level.
    statesOf(country, { depth: 1 }).then((rows) => {
      if (live) setStates(rows);
    });
    return () => {
      live = false;
    };
  }, [country]);

  useEffect(() => {
    setState("");
    setCities([]);
  }, [country]);

  function loadCities(nextState: string) {
    setState(nextState);
    if (!nextState) {
      // Without a state the endpoint answers with subdivisions, not cities.
      setCities([]);
      return;
    }
    startTransition(async () => {
      const params = new URLSearchParams({ country, state: nextState, limit: "100" });
      const res = await fetch(`/api/cities?${params}`);
      setCities(res.ok ? ((await res.json()) as { cities: CityOption[] }).cities : []);
    });
  }

  return (
    <form style={{ display: "grid", gap: "1rem", marginTop: "2rem" }}>
      <label>
        Country
        <select value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">Select…</option>
          {countries.map((c) => (
            <option key={c.iso2} value={c.iso2}>
              {c.emoji ? `${c.emoji} ` : ""}
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        Subdivision
        <select
          value={state}
          disabled={states.length === 0}
          onChange={(e) => loadCities(e.target.value)}
        >
          <option value="">{states.length ? "Select…" : "None"}</option>
          {states.map((s) => (
            <option key={s.stable_key} value={s.iso3166_2 ?? String(s.id)}>
              {s.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        City
        <select disabled={cities.length === 0}>
          <option value="">{loading ? "Loading…" : cities.length ? "Select…" : "None"}</option>
          {cities.map((c) => (
            <option key={c.id} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <p style={{ color: "#666", fontSize: "0.875rem" }}>
        {states.length} subdivisions · {cities.length} cities loaded
      </p>
    </form>
  );
}
