import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from main import app
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_screener_cache():
    """The screener response is memoised in a module-level dict keyed by query
    params. Different tests mock /api/screener with different rows under the same
    default key, so without clearing it one test can serve another's cached row.
    """
    main._screener_cache.clear()
    yield
    main._screener_cache.clear()
