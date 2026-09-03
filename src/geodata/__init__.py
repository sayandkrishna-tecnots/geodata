"""geodata -- countries, subdivisions and cities as a queryable dataset.

Two things to know before using this:

1. **Do not persist `id`.** Upstream ids are not stable across dataset
   versions: 351 state ids and 6,321 city ids changed meaning between two
   consecutive upstream releases. Persist `stable_key`, or `iso2` /
   `iso3166_2`. Every lookup here accepts those.

2. **Subdivisions nest.** The UK has 221 subdivisions across two levels.
   `states_of("GB")` gives all of them; `root_states("GB")` gives the four you
   want in a dropdown.
"""

from .api import (
    regions,
    subregions,
    cities_of,
    countries,
    find_country,
    find_language,
    get_city,
    get_country,
    get_language,
    get_state,
    languages,
    localized_name,
    root_states,
    search_cities,
    state_tree,
    states_of,
    subdivision_twin,
    substates_of,
    translations_of,
)
from ._version import (  # noqa: F401
    COUNTS, DATASET_VERSION, SOURCE_REPO, SOURCE_TAG, __version__,
)
from .exceptions import (
    Ambiguous,
    CityNotFound,
    CountryNotFound,
    GeodataError,
    LanguageNotFound,
    NotFound,
    StateNotFound,
)
# The fold is public API: a consumer building its own index -- a search box, a
# join against another dataset -- must key it exactly the way `stable_key` was
# computed, or the two will silently fail to match. `geodata-js` exports the
# same three from its root entry, and a shared fixture pins them together.
from .normalize import normalize_key, normalize_name, slugify

from .types import (
    Region,
    Subregion,
    City,
    Country,
    Language,
    State,
    StateNode,
    SubdivisionLink,
    Timezone,
)

__all__ = [
    "normalize_name",
    "normalize_key",
    "slugify",
    "__version__", "DATASET_VERSION", "SOURCE_TAG", "SOURCE_REPO", "COUNTS",
    "regions",
    "subregions",
    "Region",
    "Subregion",
    "countries", "get_country", "find_country",
    "states_of", "get_state", "state_tree", "root_states", "substates_of",
    "cities_of", "get_city", "search_cities", "subdivision_twin",
    "languages", "get_language", "find_language",
    "translations_of", "localized_name",
    "Country", "State", "City", "Language", "StateNode", "SubdivisionLink",
    "Timezone",
    "GeodataError", "NotFound", "CountryNotFound", "StateNotFound",
    "CityNotFound", "LanguageNotFound", "Ambiguous",
]
