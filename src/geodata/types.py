"""Immutable record types.

Frozen dataclasses rather than dicts: the dataset is read-only reference data,
and freezing it means a caller cannot accidentally mutate the shared cache that
every other caller in the process is reading.

Coordinates are Optional everywhere. Upstream coverage is incomplete and
(0, 0) is a placeholder the build strips, so `city.latitude is None` is a
normal case to handle, not an error (issue 7).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Timezone:
    zone_name: Optional[str]
    gmt_offset: Optional[int]
    gmt_offset_name: Optional[str]
    abbreviation: Optional[str]
    tz_name: Optional[str]


@dataclass(frozen=True)
class Language:
    """An ISO 639 language.

    The only table here whose identity is not an upstream integer: `code` is
    the identity and `stable_key` equals it, so invariant 1 (ids churn between
    releases) does not apply -- a language code is safe to persist in a FK
    column.
    """

    code: str
    name: str
    normalized_name: str
    standard: str
    stable_key: str

    @property
    def is_iso639_1(self) -> bool:
        """True for the 184 two-letter codes. Translation keys use these."""
        return self.standard == "iso639_1"


@dataclass(frozen=True)
class Region:
    """One of the six top-level regions (Africa, Americas, Asia, ...)."""

    id: int
    name: str
    normalized_name: str
    wikidata_id: Optional[str]


@dataclass(frozen=True)
class Subregion:
    """A subregion within a :class:`Region`, e.g. Western Africa."""

    id: int
    name: str
    normalized_name: str
    region_id: int
    wikidata_id: Optional[str]


@dataclass(frozen=True)
class SubdivisionLink:
    """A territory's other identity, as a subdivision of another country.

    Martinique is both country `MQ` and French subdivision `FR-MQ`. Neither
    representation is canonical; both are first-class (Decision 3).
    """

    country_iso2: str
    state_id: int
    state_stable_key: Optional[str]
    iso3166_2: Optional[str]
    type: Optional[str]


@dataclass(frozen=True)
class Country:
    id: int
    iso2: str
    iso3: Optional[str]
    numeric_code: Optional[str]
    name: str
    normalized_name: str
    native: Optional[str]
    capital: Optional[str]
    phone_code: Optional[str]
    currency: Optional[str]
    currency_name: Optional[str]
    currency_symbol: Optional[str]
    tld: Optional[str]
    region: Optional[str]
    region_id: Optional[int]
    subregion: Optional[str]
    subregion_id: Optional[int]
    nationality: Optional[str]
    population: Optional[int]
    gdp: Optional[int]
    area_sq_km: Optional[int]
    postal_code_format: Optional[str]
    postal_code_regex: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    emoji: Optional[str]
    emoji_unicode: Optional[str]
    wikidata_id: Optional[str]
    timezones: Tuple[Timezone, ...]
    stable_key: str
    also_subdivision_of: Optional[SubdivisionLink]
    state_count: int
    city_count: int
    has_states: bool
    has_cities: bool

    @property
    def is_also_a_subdivision(self) -> bool:
        return self.also_subdivision_of is not None


@dataclass(frozen=True)
class State:
    id: int
    country_id: int
    country_iso2: str
    name: str
    normalized_name: str
    native: Optional[str]
    state_code: Optional[str]
    iso3166_2: Optional[str]
    fips_code: Optional[str]
    type: Optional[str]
    level: Optional[int]
    parent_id: Optional[int]
    depth: int
    latitude: Optional[float]
    longitude: Optional[float]
    timezone: Optional[str]
    population: Optional[int]
    wikidata_id: Optional[str]
    stable_key: str
    city_count: int
    has_cities: bool

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


@dataclass(frozen=True)
class City:
    id: int
    state_id: int
    country_id: int
    country_iso2: str
    state_code: Optional[str]
    state_iso3166_2: Optional[str]
    name: str
    normalized_name: str
    latitude: Optional[float]
    longitude: Optional[float]
    timezone: Optional[str]
    stable_key: str


@dataclass(frozen=True)
class StateNode:
    """A state plus its children, for `state_tree()`."""

    state: State
    children: Tuple["StateNode", ...] = field(default_factory=tuple)

    def walk(self):
        """Yield this node's state and every descendant, depth-first."""
        yield self.state
        for child in self.children:
            for s in child.walk():
                yield s
