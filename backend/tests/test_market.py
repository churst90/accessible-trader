import pytest
from app import create_app

@pytest.fixture
def app():
    return create_app()

@pytest.mark.asyncio
async def test_get_symbols(client):
    response = await client.get("/market/get_symbols?market=crypto&symbol=BTC/USD")
    assert response.status_code == 200
    data = await response.get_json()
    assert data["success"]
    assert "symbols" in data
