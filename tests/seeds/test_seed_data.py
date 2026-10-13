"""Validation of the version-controlled seed files (no database needed)."""
import json
import shutil

import pytest

from src.seeds.__main__ import main
from src.seeds.seeder import DATA_DIR, SeedValidationError, load_seed_data


def test_shipped_seed_files_are_valid():
    data = load_seed_data()
    assert len(data["states"]) == 28
    assert sum(len(s["districts"]) for s in data["states"]) == 491
    assert set(data["roles"]) == {"farmer", "vendor", "admin"}
    assert len(data["checksum"]) == 64


def test_locations_match_tables_script_without_the_duplicated_block():
    data = load_seed_data()
    nagaland = next(s for s in data["states"] if s["name"] == "Nagaland")
    assert len(nagaland["districts"]) == len(set(nagaland["districts"])) == 11


def test_lookups_cover_every_value_the_code_requires():
    from src.data_models.orders_model import ORDER_STATUSES
    from src.data_models.transactions_model import PAYMENT_STATE_NAMES

    misc = load_seed_data()["misc"]
    assert set(ORDER_STATUSES) <= set(misc["order_status"])
    assert set(PAYMENT_STATE_NAMES) <= set(misc["payment_status"])
    assert {"active", "inactive", "suspended"} <= set(misc["status"])
    assert misc["answer"] == ["yes"]


@pytest.fixture
def data_copy(tmp_path):
    for name in ("lookups.json", "locations.json"):
        shutil.copy(DATA_DIR / name, tmp_path / name)
    return tmp_path


def _edit(path, mutate):
    content = json.loads(path.read_text(encoding="utf-8"))
    mutate(content)
    path.write_text(json.dumps(content), encoding="utf-8")


def test_duplicate_district_is_rejected(data_copy):
    _edit(data_copy / "locations.json", lambda d: d["states"][0]["districts"].append(d["states"][0]["districts"][0].upper()))
    with pytest.raises(SeedValidationError, match="duplicate district"):
        load_seed_data(data_copy)


def test_duplicate_state_is_rejected(data_copy):
    _edit(data_copy / "locations.json", lambda d: d["states"].append({"name": " goa ", "districts": []}))
    with pytest.raises(SeedValidationError, match="duplicate state"):
        load_seed_data(data_copy)


def test_duplicate_lookup_value_is_rejected(data_copy):
    _edit(data_copy / "lookups.json", lambda d: d["miscellaneous_data"]["status"].append("active"))
    with pytest.raises(SeedValidationError, match="duplicate values"):
        load_seed_data(data_copy)


def test_malformed_file_is_rejected(data_copy):
    (data_copy / "lookups.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SeedValidationError, match="Cannot read"):
        load_seed_data(data_copy)


def test_cli_rejects_unknown_dataset(capsys):
    assert main(["--only", "unknown"]) == 2
    assert "unknown dataset" in capsys.readouterr().err
