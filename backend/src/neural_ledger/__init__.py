"""Neural Ledger: an AI cash-flow copilot with deterministic authority.

Layers (dependencies point inward only):
    domain       pure business rules, standard library only
    application  use cases and ports (interfaces), standard library only
    adapters     HTTP, CLI, LLM providers, decision models, persistence, sandbox bank
    bootstrap    the only place that wires concrete adapters into use cases
"""

__version__ = "0.1.0"
