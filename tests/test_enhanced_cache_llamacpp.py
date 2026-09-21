"""Cache hierarchy, persistence, limits, and corrupt-entry recovery."""

import tempfile
import unittest

from enhanced_support import load_variant

module = load_variant("enhanced-cache-llamacpp", "cache")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def cache(self, ram=48, disk=4096, namespace="model-a"):
        cache = module.TieredCache(self.directory.name, namespace, ram, disk)
        self.addCleanup(cache.close)
        return cache

    def snapshot(self, tokens, value=b"abcdefgh"):
        return module.Snapshot(tuple(tokens), value)

    def test_ram_eviction_spills_and_disk_hit_promotes(self):
        cache = self.cache()
        a, b = self.snapshot([1, 2, 3]), self.snapshot([4, 5, 6])
        cache.put(a)
        self.assertEqual(cache.get([1, 2, 9]), a)
        cache.put(b)
        self.assertIn(a.tokens, cache.disk)
        self.assertEqual(cache.get([1, 2, 3, 9]), a)
        self.assertIn(a.tokens, cache.ram)
        self.assertIn(b.tokens, cache.disk)
        self.assertEqual(cache.stats["ram_hits"], 1)
        self.assertEqual(cache.stats["disk_hits"], 1)
        self.assertLessEqual(cache.ram_bytes, cache.ram_limit)

    def test_longest_prefix_and_threshold(self):
        cache = self.cache(ram=1024)
        a, b = self.snapshot([1, 2, 3]), self.snapshot([1, 2, 4, 5])
        cache.put(a)
        cache.put(b)
        self.assertEqual(cache.get([1, 2, 4, 6]), b)
        self.assertIsNone(cache.get([1, 7], min_prefix=2))

    def test_restart_flushes_ram_and_isolates_models(self):
        cache = self.cache()
        snapshot = self.snapshot([1, 2, 3])
        cache.put(snapshot)
        cache.close()
        restarted = self.cache()
        self.assertEqual(restarted.get([1, 2, 3]), snapshot)
        self.assertEqual(restarted.stats["disk_hits"], 1)
        self.assertIsNone(self.cache(namespace="model-b").get([1, 2, 3]))

    def test_disk_lru_budget_and_oversized_entry(self):
        cache = self.cache(ram=0, disk=250)
        a, b, c = [self.snapshot([x]) for x in [1, 2, 3]]
        cache.put(a)
        cache.put(b)
        self.assertEqual(cache.get([1]), a)
        cache.put(c)
        self.assertIsNone(cache.get([2]))
        self.assertEqual(cache.get([1]), a)
        cache.put(self.snapshot([4], b"x" * 1024))
        self.assertIsNone(cache.get([4]))
        self.assertLessEqual(cache.disk_bytes, cache.disk_limit)
        self.assertEqual(cache.disk_bytes, sum(p.stat().st_size for p in cache.directory.glob("*.kv")))

    def test_corruption_is_a_miss_and_other_entries_survive(self):
        cache = self.cache(ram=0)
        a, b = self.snapshot([1, 2]), self.snapshot([3, 4])
        cache.put(a)
        cache.put(b)
        path = cache.disk[a.tokens][0]
        data = path.read_bytes()
        path.write_bytes(data[:-1] + b"!")
        self.assertIsNone(cache.get(a.tokens))
        self.assertEqual(cache.get(b.tokens), b)
        self.assertFalse(path.exists())
        (cache.directory / "broken.kv").write_bytes(b"incomplete")
        cache.close()
        restarted = self.cache(ram=0)
        self.assertEqual(restarted.get(b.tokens), b)
        self.assertFalse((restarted.directory / "broken.kv").exists())

    def test_single_writer_and_disabled_cache(self):
        cache = self.cache(ram=0, disk=0)
        with self.assertRaisesRegex(RuntimeError, "already in use"):
            self.cache()
        cache.put(self.snapshot([1]))
        self.assertIsNone(cache.get([1]))
        self.assertEqual(cache.ram_bytes + cache.disk_bytes, 0)


if __name__ == "__main__":
    unittest.main()
