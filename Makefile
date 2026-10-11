.PHONY: install test test-golden test-security demo evidence api up

PY ?= python3

install:            ## install backend with API and dev extras (use a virtualenv)
	cd backend && $(PY) -m pip install -e ".[api,dev,pdf]"

test:               ## full suite: architecture, golden, unit, security, contracts, adapters, HTTP
	cd backend && $(PY) -m pytest

test-golden:
	cd backend && $(PY) -m pytest -m golden -v

test-security:
	cd backend && $(PY) -m pytest -m security -v

demo:               ## run the six-scene demo arc offline in the terminal
	cd backend && NL_CLOCK=fixed NL_IDS=sequential PYTHONPATH=src $(PY) -m neural_ledger.bootstrap.cli demo

evidence:           ## demo + audit export + junit test results into evidence/
	cd backend && NL_CLOCK=fixed NL_IDS=sequential PYTHONPATH=src $(PY) -m neural_ledger.bootstrap.cli demo-and-export --out ../evidence/sandbox-logs/audit.jsonl
	cd backend && $(PY) -m pytest --junitxml=../evidence/test-results/junit.xml

api:                ## run the API locally on :8000
	cd backend && PYTHONPATH=src $(PY) -m uvicorn neural_ledger.bootstrap.asgi:app --reload --port 8000

up:                 ## the submission path: docker compose, no keys needed
	docker compose up --build
