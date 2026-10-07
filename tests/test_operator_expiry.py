import asyncio

from python.operator_expiry import OperatorExpiryManager


def test_expiry_restores_original_state():
    async def scenario():
        restored = asyncio.Event()
        captured = []

        async def restore(key, state):
            captured.append((key, state))
            restored.set()

        manager = OperatorExpiryManager(restore)
        manager.activate("vip", 0.03, {"vip_enabled": False, "vip_corridor": None})
        assert manager.public_record("vip")["status"] == "ACTIVE"
        await asyncio.wait_for(restored.wait(), timeout=1)
        await manager.stop()
        assert captured == [("vip", {"vip_enabled": False, "vip_corridor": None})]
        assert manager.public_record("vip") is None

    asyncio.run(scenario())


def test_timer_snapshot_excludes_private_restore_payload():
    async def scenario():
        manager = OperatorExpiryManager(lambda key, state: asyncio.sleep(0))
        record = manager.activate("construction", 10, {"private": "state"})
        assert record["duration_seconds"] == 10
        assert "original_state" not in record
        await manager.stop()

    asyncio.run(scenario())
