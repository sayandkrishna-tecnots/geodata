"""Deterministic normalization shared by every geodata build step.

`normalized_name` is part of the stable-key strategy (Decision 2), so it must
behave identically in Python and JS. `tests/fixtures/normalize.json` is the
conformance fixture both implementations run against -- change this file and
you must regenerate that fixture.

Algorithm (in order):
  1. NFKD decompose
  2. drop combining marks -- but only where the base character is not Cyrillic
     (see below), then recompose NFC
  3. casefold
  4. map connectors/punctuation to a single space
  5. drop remaining non-alphanumeric characters, in ANY script
  6. collapse whitespace, strip

Step 5 is script-preserving, not transliterating: 'Октябрьский' folds to
'октябрьский', not 'oktyabrskiy'. Folding to Latin would require a
transliteration table per script and would make the key lossy and ambiguous.
The key's job is to match a name to itself across dataset versions, and the
name is stable in its own script.

Step 2 is script-aware for the same reason. In Latin script a diacritic is a
decoration (e/e are the same letter), so stripping it is the right fold. In
Cyrillic it is not: NFKD decomposes 'й' into 'и' + breve and 'ё' into 'е' +
diaeresis, but those are distinct letters of the alphabet, and blindly
stripping would collide 'Октябрьский' with a hypothetical 'Октябрьскии'. So
combining marks over a Cyrillic base are kept and recomposed.
"""

import re
import unicodedata

__all__ = ["normalize_name", "normalize_key", "slugify", "clean_text"]

# Characters that separate words rather than belong to them.
_SEPARATORS = re.compile(r"[\s\-‐-―_/\\.,;:()\[\]{}'‘’\"“”`]+")
# Anything still not alphanumeric after separator handling. `\w` under
# re.UNICODE keeps letters and digits of every script; we exclude `_` because
# the separator pass already turned it into a space.
_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)
# ASCII-only variant, for codes (iso2, iso3166_2) which are ASCII by definition.
_NON_ALNUM_ASCII = re.compile(r"[^0-9a-z]+")
_WS = re.compile(r"\s+")

# Unicode blocks where a combining mark is part of the letter, not a decoration.
_MARK_BEARING_SCRIPTS = ("CYRILLIC",)

# Mojibake signatures -- these mean an upstream file was decoded as latin-1.
MOJIBAKE = ("Ã©", "Ã¨", "Ã¡", "Ã­", "Ã³", "Ãº", "Ã±", "â€™", "â€œ", "â€\x9d", "Â ", "Ã\x83")

_HTML_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")


def clean_text(value):
    """Normalize a human-readable string for storage: NFC, trimmed, single spaces.

    Preserves accents and case -- this is the display form, not the key form.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = unicodedata.normalize("NFC", value)
    value = value.replace(" ", " ").replace("​", "")
    value = _WS.sub(" ", value).strip()
    return value or None


def _is_mark_bearing(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return name.startswith(_MARK_BEARING_SCRIPTS)


def _strip_decorative_marks(value):
    """NFKD, drop combining marks except over a mark-bearing script, then NFC."""
    out = []
    base = ""
    for ch in unicodedata.normalize("NFKD", value):
        if unicodedata.combining(ch):
            if _is_mark_bearing(base):
                out.append(ch)
            continue
        base = ch
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalize_name(value):
    """Fold a place name to its comparison key.

    >>> normalize_name("Saint-Étienne")
    'saint etienne'
    >>> normalize_name("  N'Djamena ")
    'n djamena'
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = _strip_decorative_marks(value)
    value = value.casefold()
    value = _SEPARATORS.sub(" ", value)
    value = _NON_ALNUM.sub(" ", value).replace("_", " ")
    return _WS.sub(" ", value).strip()


def normalize_key(value):
    """Fold a code (iso2, iso3166_2, state_code) to its comparison key."""
    if value is None:
        return ""
    return _NON_ALNUM_ASCII.sub("", str(value).casefold())


def slugify(value):
    """URL-safe form of a place name."""
    return normalize_name(value).replace(" ", "-")


def has_mojibake(value):
    if not isinstance(value, str):
        return False
    return any(sig in value for sig in MOJIBAKE)


def has_html_entity(value):
    if not isinstance(value, str):
        return False
    return bool(_HTML_ENTITY.search(value))
