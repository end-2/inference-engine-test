"""Bounded JSON metadata followed by a safetensors payload, without pickle."""

import json
import struct


CONTENT_TYPE = "application/x-pd-state"
MAX_HEADER = 128 * 1024


def pack(metadata, tensors):
    header = json.dumps({**metadata, "version": 1}, allow_nan=False).encode()
    if len(header) > MAX_HEADER:
        raise ValueError("State metadata is too large")
    return struct.pack("!I", len(header)) + header + tensors


def unpack(payload):
    if len(payload) < 4:
        raise ValueError("Truncated state")
    length = struct.unpack("!I", payload[:4])[0]
    if not 0 < length <= MAX_HEADER or len(payload) <= length + 4:
        raise ValueError("Invalid state header length")
    try:
        metadata = json.loads(payload[4:4 + length])
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid state metadata") from exc
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Unsupported state protocol")
    return metadata, payload[4 + length:]


async def read_limited(chunks, limit):
    data = bytearray()
    async for chunk in chunks:
        if len(data) + len(chunk) > limit:
            raise ValueError("Request or state exceeds the configured byte limit")
        data.extend(chunk)
    return bytes(data)
