"""Bounded RAM LRU with disk spill, promotion, and persistent prefix lookup."""

from collections import OrderedDict
from dataclasses import dataclass
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import tempfile


MAGIC = b"LKV00001"
HEADER_LIMIT = 1024 * 1024


def common_prefix(left, right):
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right))


@dataclass(frozen=True)
class Snapshot:
    tokens: tuple[int, ...]
    state: bytes

    @property
    def size(self):
        # Budget the native payload and token IDs; index/container overhead is separate.
        return len(self.state) + len(self.tokens) * 8


class TieredCache:
    def __init__(self, directory, namespace, ram_bytes, disk_bytes):
        if ram_bytes < 0 or disk_bytes < 0:
            raise ValueError("Cache budgets must not be negative")
        self.directory = Path(directory) / hashlib.sha256(namespace.encode()).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / ".lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("Cache directory is already in use") from None
        self.ram_limit, self.disk_limit = ram_bytes, disk_bytes
        self.ram, self.disk = OrderedDict(), OrderedDict()
        self.ram_bytes = self.disk_bytes = 0
        self.stats = dict(ram_hits=0, disk_hits=0, misses=0, spills=0, evictions=0, errors=0)
        try:
            for path in self.directory.glob(".tmp-*"):
                path.unlink()
            for path in sorted(self.directory.glob("*.kv"), key=lambda p: p.stat().st_mtime_ns):
                try:
                    with path.open("rb") as source:
                        tokens, _, _ = self._header(source)
                    if path.stem != self._key(tokens):
                        raise ValueError("Cache key mismatch")
                    size = path.stat().st_size
                    self.disk[tokens] = (path, size)
                    self.disk_bytes += size
                except (OSError, ValueError, KeyError, TypeError, struct.error):
                    path.unlink(missing_ok=True)
                    self.stats["errors"] += 1
            self._trim_disk()
        except BaseException:
            self.lock.close()
            raise

    @staticmethod
    def _key(tokens):
        return hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _header(source):
        if source.read(len(MAGIC)) != MAGIC:
            raise ValueError("Unknown cache format")
        length = struct.unpack("<I", source.read(4))[0]
        if length > HEADER_LIMIT:
            raise ValueError("Invalid cache header length")
        header = json.loads(source.read(length))
        tokens = tuple(header["tokens"])
        if not tokens or any(type(token) is not int or token < 0 for token in tokens):
            raise ValueError("Invalid cached tokens")
        return tokens, header["sha256"], header["size"]

    def get(self, prompt, min_prefix=1):
        while True:
            best, length = None, min_prefix - 1
            for tokens in list(self.ram) + list(self.disk):
                shared = common_prefix(tokens, prompt)
                if shared > length:
                    best, length = tokens, shared
            if best is None:
                self.stats["misses"] += 1
                return None
            if best in self.ram:
                self.ram.move_to_end(best)
                self.stats["ram_hits"] += 1
                return self.ram[best]
            path, size = self.disk[best]
            try:
                with path.open("rb") as source:
                    tokens, digest, state_size = self._header(source)
                    state = source.read(size + 1)
                if tokens != best or len(state) != state_size or hashlib.sha256(state).hexdigest() != digest:
                    raise ValueError("Corrupt cache snapshot")
                snapshot = Snapshot(tokens, state)
            except (OSError, ValueError, KeyError, TypeError, struct.error):
                self._drop_disk(best)
                self.stats["errors"] += 1
                continue
            self.stats["disk_hits"] += 1
            if snapshot.size <= self.ram_limit:
                self._drop_disk(best)
                self.put(snapshot)
            else:
                self.disk.move_to_end(best)
                os.utime(path, None)
            return snapshot

    def put(self, snapshot):
        if snapshot.tokens in self.ram:
            self.ram_bytes -= self.ram.pop(snapshot.tokens).size
        if snapshot.tokens in self.disk:
            self._drop_disk(snapshot.tokens)
        if snapshot.size > self.ram_limit:
            self._store_disk(snapshot)
            return
        self.ram[snapshot.tokens] = snapshot
        self.ram_bytes += snapshot.size
        while self.ram_bytes > self.ram_limit:
            _, old = self.ram.popitem(last=False)
            self.ram_bytes -= old.size
            self._store_disk(old)

    def discard(self, tokens):
        if tokens in self.ram:
            self.ram_bytes -= self.ram.pop(tokens).size
        if tokens in self.disk:
            self._drop_disk(tokens)

    def _drop_disk(self, tokens):
        path, size = self.disk.pop(tokens)
        self.disk_bytes -= size
        path.unlink(missing_ok=True)

    def _trim_disk(self):
        while self.disk_bytes > self.disk_limit:
            self._drop_disk(next(iter(self.disk)))
            self.stats["evictions"] += 1

    def _store_disk(self, snapshot):
        if not self.disk_limit:
            return
        header = json.dumps({"tokens": snapshot.tokens, "size": len(snapshot.state),
                             "sha256": hashlib.sha256(snapshot.state).hexdigest()},
                            separators=(",", ":")).encode()
        size = len(MAGIC) + 4 + len(header) + len(snapshot.state)
        if size > self.disk_limit or len(header) > HEADER_LIMIT:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".tmp-", delete=False) as target:
                temporary = Path(target.name)
                target.write(MAGIC + struct.pack("<I", len(header)) + header)
                target.write(snapshot.state)
                target.flush()
                os.fsync(target.fileno())
            path = self.directory / (self._key(snapshot.tokens) + ".kv")
            os.replace(temporary, path)
            if snapshot.tokens in self.disk:
                self.disk_bytes -= self.disk.pop(snapshot.tokens)[1]
            self.disk[snapshot.tokens] = (path, size)
            self.disk_bytes += size
            self.stats["spills"] += 1
            self._trim_disk()
        except OSError:
            self.stats["errors"] += 1
            logging.exception("KV cache disk write failed")
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def close(self):
        if self.lock.closed:
            return
        try:
            for snapshot in self.ram.values():
                self._store_disk(snapshot)
            self.ram.clear()
            self.ram_bytes = 0
        finally:
            self.lock.close()
