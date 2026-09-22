import os

import pytest
import requests


BASE = os.getenv("TEST_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def live_stack():
    if os.getenv("INTEGRATION") != "1":
        pytest.skip("set INTEGRATION=1 to run live-stack tests")
    try:
        response = requests.get(f"{BASE}/health", timeout=3)
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError(response.text)
    except Exception as exc:
        pytest.fail(f"integration stack is unavailable: {exc}")
    return BASE
