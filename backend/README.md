# neural-ledger (backend)

The Python package behind Neural Ledger, an AI cash-flow copilot with deterministic authority
(FinTechathon 2026, Topic A). The product, setup and demo are documented in the root
[README](../README.md); architecture and scope live in `docs/`.

The core (`domain/` + `application/`) has no runtime dependencies. The `api` extra adds FastAPI
and uvicorn; the `dev` extra adds the test tooling.

```bash
pip install -e ".[api,dev]"   # from backend/, inside a virtualenv (or `make install` from the root)
python -m pytest              # fast lane: property tests deselected
python -m pytest -m property  # only the hypothesis property tests
python -m pytest -m ""        # full suite: required for CI and PRs (`make test-all`)
```
