# geodata -- dataset pipeline
#
# Ordinary refresh:   make refresh && make check
# Cut a release:      make release VERSION=2026.10
#
# `make check` is what CI runs. It must pass before any artifact is published.

PY ?= python3
VERSION ?= $(shell $(PY) -c "import json;print(json.load(open('data/RELEASE.json'))['version'])" 2>/dev/null)

.PHONY: help fetch build validate churn test check refresh release clean-cache \
	conformance js js-build js-test js-pack js-publish-dry

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

conformance: ## regenerate the shared JS/Python conformance corpus
	python3 scripts/build_conformance.py

# --- JS package (packages/js) -------------------------------------------------
# `js` is the whole gate: generate from data/canonical, typecheck, build both
# module formats, run the suite, then lint the published shape. `npm test`
# alone would pass on a package that no consumer can actually import.

js: js-build js-test ## generate, build and test the npm package

js-build: ## data/canonical -> packages/js/src/{data,country}, then dist/
	python3 scripts/build_js.py
	cd packages/js && npm run typecheck && npm run build

js-test: ## vitest, publint, attw, and an install-from-tarball smoke test
	cd packages/js && npm test && npm run lint:pkg && bash scripts/smoke.sh

js-pack: js-build ## produce the tarball without publishing
	cd packages/js && npm pack

js-publish-dry: js-build ## everything publish does, except publishing
	cd packages/js && npm publish --dry-run --access public

clean-cache: ## drop the upstream download cache (~53 MB)
	rm -rf .cache/upstream
