.PHONY: install test test-all test-property test-golden test-security test-suitability demo demo-ledger ledgers backtest evidence api up

PY ?= python3

install:            ## install backend with API and dev extras (use a virtualenv)
	cd backend && $(PY) -m pip install -e ".[api,dev,pdf,ml]"

test:               ## fast lane: everything except the hypothesis property tests (for iteration)
	cd backend && $(PY) -m pytest

test-all:           ## full suite, property tests included: required for CI and before every PR
	cd backend && $(PY) -m pytest -m ""

test-property:      ## only the hypothesis property tests
	cd backend && $(PY) -m pytest -m property

test-golden:
	cd backend && $(PY) -m pytest -m golden -v

test-security:
	cd backend && $(PY) -m pytest -m security -v

test-suitability:   ## hard rules H1-H5 and the suitability checks (docs/SECURITY.md, "Suitability")
	cd backend && $(PY) -m pytest -m suitability -v

demo:               ## run the six-scene demo arc offline in the terminal
	cd backend && NL_CLOCK=fixed NL_IDS=sequential PYTHONPATH=src $(PY) -m neural_ledger.bootstrap.cli demo

demo-ledger:        ## the same demo arc, with the model estimated from data/ledgers (stage 1)
	cd backend && NL_MODEL_SOURCE=ledger NL_CLOCK=fixed NL_IDS=sequential PYTHONPATH=src $(PY) -m neural_ledger.bootstrap.cli demo

ledgers:            ## regenerate data/ledgers/*.json (deterministic, seeded)
	cd backend && PYTHONPATH=src:. $(PY) -m tests.fixtures.ledger_generator --out ../data/ledgers

backtest:           ## synthetic implementation validation (100 seeded ledgers per source)
	cd backend && PYTHONPATH=src:. $(PY) -m tests.backtest.run --seeds 100 --out ../evidence/backtest/synthetic_backtest.json

evidence:           ## demo + audit export + junit results of the FULL suite into evidence/
	cd backend && NL_CLOCK=fixed NL_IDS=sequential PYTHONPATH=src $(PY) -m neural_ledger.bootstrap.cli demo-and-export --out ../evidence/sandbox-logs/audit.jsonl
	cd backend && $(PY) -m pytest -m "" --junitxml=../evidence/test-results/junit.xml

api:                ## run the API locally on :8000
	cd backend && PYTHONPATH=src $(PY) -m uvicorn neural_ledger.bootstrap.asgi:app --reload --port 8000

up:                 ## the submission path: docker compose, no keys needed
	docker compose up --build
