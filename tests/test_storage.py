import tempfile
import unittest
from pathlib import Path

from pcslow.scenarios import scenario
from pcslow.storage import MetricStore


class StorageTests(unittest.TestCase):
    def test_snapshots_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MetricStore(Path(temp) / "pcslow.db")
            snapshots = scenario("memory")
            for snapshot in snapshots:
                store.add_snapshot(snapshot)

            loaded = store.recent_snapshots(limit=10)

            self.assertEqual(len(loaded), len(snapshots))
            self.assertEqual(loaded[-1].memory_used_percent, snapshots[-1].memory_used_percent)


if __name__ == "__main__":
    unittest.main()
