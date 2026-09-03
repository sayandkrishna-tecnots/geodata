# geodata -- dataset pipeline
#
# Ordinary refresh:   make refresh && make check
# Cut a release:      make release VERSION=2026.10
#
# `make check` is what CI runs. It must pass before any artifact is published.

PY ?= python3
VERSION ?= $(shell $(PY) -c "import json;print(json.load(open('data/RELEASE.json'))['version'])" 2>/dev/null)

.PHONY: help fetch build validate churn test check refresh release clean-cache

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t24

fetch:  ## download the pinned upstream tag and write data/SOURCE.lock
	$(PY) scripts/fetch.py

verify: ## re-hash the upstream cache against SOURCE.lock, no network
	$(PY) scripts/fetch.py --verify-only

build:  ## map upstream -> data/canonical/*.ndjson
	$(PY) scripts/build_canonical.py

validate: ## the hard gate: 8 checks over data/canonical
	$(PY) scripts/validate.py

churn:  ## diff the last release against the working canonical set
	$(PY) scripts/churn.py --from data/snapshots/$(VERSION) \
		--from-label $(VERSION) --to-label dev --fail-on-breach

test:   ## unit + integrity + regression tests
	$(PY) -m pytest tests/ -q

check: validate test ## everything CI runs

refresh: fetch build validate ## pull upstream, rebuild, gate

release: ## snapshot + baseline; requires VERSION=
	@test -n "$(VERSION)" || (echo "usage: make release VERSION=2026.10"; exit 1)
	$(PY) scripts/release.py --version $(VERSION)

clean-cache: ## drop the upstream download cache (~53 MB)
	rm -rf .cache/upstream
