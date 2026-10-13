import json

import jsonschema
import pytest

from tests.backtest import run as bt
from tests.conftest import CONTRACTS, REPO

SCHEMA = json.loads((CONTRACTS / "backtest/synthetic_backtest.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


@pytest.fixture(scope="module")
def small_run():
    return bt.run(2, reference_trials=100)


def test_schema_is_valid_and_small_run_conforms(small_run):
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    VALIDATOR.validate(small_run)


def test_committed_evidence_conforms_to_the_same_schema():
    artifact = json.loads((REPO / "evidence/backtest/synthetic_backtest.json").read_text(encoding="utf-8"))
    VALIDATOR.validate(artifact)
    assert artifact["reference"]["trials_per_cell"] == bt.DEFAULT_TRIALS


def test_schema_rejects_missing_reference_and_bad_cell_window(small_run):
    without_reference = {key: value for key, value in small_run.items() if key != "reference"}
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(without_reference)
    altered = json.loads(bt.render(small_run))
    altered["reference"]["cells"]["spend_p80"]["A.6.groceries"]["window_n"] = 0
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(altered)


@pytest.mark.parametrize("field,value", [("observed_hits", "bad"), ("trials", 0), ("mc_se", -1)])
def test_schema_rejects_malformed_reference_cell(small_run, field, value):
    altered = json.loads(bt.render(small_run))
    altered["reference"]["cells"]["spend_p80"]["A.6.groceries"][field] = value
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(altered)
