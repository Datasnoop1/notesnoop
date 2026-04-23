from pathlib import Path
import asyncio
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers.companies import network


async def _run_person_center_test() -> None:
    original_fetch_all = network.fetch_all
    original_fetch_one = network.fetch_one
    original_fetch_entity_names = network._fetch_entity_names

    def fake_fetch_one(query, params):
        return None

    def fake_fetch_all(query, params):
        normalized = " ".join(query.split())
        if "FROM administrator WHERE name = %s GROUP BY enterprise_number, role" in normalized:
            return [
                {
                    "enterprise_number": "0403091121",
                    "role": "fct:m13",
                    "is_active": True,
                    "last_mandate_end": None,
                }
            ]
        if "FROM shareholder WHERE name = %s" in normalized:
            return []
        return []

    def fake_fetch_entity_names(cbes):
        return {"0403091121": "ECOLAB"}

    try:
        network.fetch_one = fake_fetch_one
        network.fetch_all = fake_fetch_all
        network._fetch_entity_names = fake_fetch_entity_names

        result = await network.get_deep_network("person:Wim De Paepe", depth=1)
        nodes = {node["id"]: node for node in result["nodes"]}

        assert "person:Wim De Paepe" in nodes
        assert nodes["person:Wim De Paepe"]["type"] == "person"
        assert nodes["0403091121"]["name"] == "ECOLAB"
        assert any(
            edge["source"] == "person:Wim De Paepe"
            and edge["target"] == "0403091121"
            and edge["relationship"] == "administrator"
            for edge in result["edges"]
        )
        assert result["depth_reached"] == 1
    finally:
        network.fetch_one = original_fetch_one
        network.fetch_all = original_fetch_all
        network._fetch_entity_names = original_fetch_entity_names


if __name__ == "__main__":
    asyncio.run(_run_person_center_test())
    print("ok")
