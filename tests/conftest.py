"""pytest configuration."""

import os
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session", autouse=True)
def isolate_persistent_state(tmp_path_factory):
    previous = os.environ.get("ASMR_HELPER_STATE_DB")
    state_dir = tmp_path_factory.mktemp("asmr-helper-state")
    os.environ["ASMR_HELPER_STATE_DB"] = str(state_dir / "state.sqlite3")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ASMR_HELPER_STATE_DB", None)
        else:
            os.environ["ASMR_HELPER_STATE_DB"] = previous
