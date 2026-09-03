"""Version identifiers, read from the dataset release manifest.

Two numbers, deliberately separate:

* ``__version__`` moves when the *code* changes.
* ``DATASET_VERSION`` moves only when the *data* does.

Both are also exported by the npm package, and CI asserts the two artifacts
agree -- that is guarantee 1 of the multi-stack plan. Reading them from
``data/RELEASE.json`` rather than hard-coding them means a release cannot ship
with the pair out of step.
"""

import json
import os

from . import loader

__all__ = ["__version__", "DATASET_VERSION", "SOURCE_TAG", "SOURCE_REPO", "COUNTS"]

# Code version. Independent of the dataset: a bug fix against dataset 2026.09
# is 2026.9.1, and the dataset version does not move.
__version__ = "2026.9.0"


def _release():
    """The release manifest, from the packaged data dir or the repo."""
    candidates = [
        os.path.join(loader.data_dir(), "RELEASE.json"),
        os.path.join(os.path.dirname(loader.data_dir()), "RELEASE.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    raise RuntimeError(
        "geodata cannot find RELEASE.json. Looked in:\n  " + "\n  ".join(candidates)
    )


_RELEASE = _release()

DATASET_VERSION = _RELEASE["version"]
SOURCE_TAG = _RELEASE["source"]["tag"]
SOURCE_REPO = _RELEASE["source"]["repo"]
COUNTS = dict(_RELEASE["counts"])
