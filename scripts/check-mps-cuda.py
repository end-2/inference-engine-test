"""Keep a verified CUDA allocation alive until the MPS smoke controller releases it."""

import ctypes as ct
import json
import os
from pathlib import Path
import time


def main():
    pipe = os.environ.get("CUDA_MPS_PIPE_DIRECTORY")
    if not pipe:
        raise RuntimeError("Device plugin did not inject CUDA_MPS_PIPE_DIRECTORY")
    cuda = ct.CDLL("libcuda.so.1")
    signatures = {
        "cuInit": [ct.c_uint],
        "cuDeviceGet": [ct.POINTER(ct.c_int), ct.c_int],
        "cuDevicePrimaryCtxRetain": [ct.POINTER(ct.c_void_p), ct.c_int],
        "cuDevicePrimaryCtxRelease_v2": [ct.c_int],
        "cuCtxSetCurrent": [ct.c_void_p],
        "cuMemAlloc_v2": [ct.POINTER(ct.c_uint64), ct.c_size_t],
        "cuMemFree_v2": [ct.c_uint64],
        "cuMemsetD8_v2": [ct.c_uint64, ct.c_ubyte, ct.c_size_t],
        "cuMemcpyDtoH_v2": [ct.c_void_p, ct.c_uint64, ct.c_size_t],
        "cuCtxSynchronize": [],
        "cuGetErrorString": [ct.c_int, ct.POINTER(ct.c_char_p)],
    }
    for name, args in signatures.items():
        getattr(cuda, name).argtypes = args
        getattr(cuda, name).restype = ct.c_int

    def call(name, *args):
        result = getattr(cuda, name)(*args)
        if result:
            message = ct.c_char_p()
            cuda.cuGetErrorString(result, ct.byref(message))
            raise RuntimeError(f"{name} failed ({result}): {message.value!r}")

    device, context, pointer = ct.c_int(), ct.c_void_p(), ct.c_uint64()
    call("cuInit", 0)
    call("cuDeviceGet", ct.byref(device), 0)
    call("cuDevicePrimaryCtxRetain", ct.byref(context), device)
    try:
        call("cuCtxSetCurrent", context)
        size = 65536
        call("cuMemAlloc_v2", ct.byref(pointer), size)
        call("cuMemsetD8_v2", pointer, 42, size)
        host = (ct.c_ubyte * size)()
        call("cuMemcpyDtoH_v2", host, pointer, size)
        call("cuCtxSynchronize")
        if bytes(host) != bytes([42]) * size:
            raise RuntimeError("CUDA memory round trip returned incorrect data")
        print(json.dumps({"status": "ready", "pod": os.environ.get("HOSTNAME"),
                          "mps_pipe": pipe, "cuda_verified_bytes": size}), flush=True)
        Path("/tmp/mps-ready").touch()
        deadline = time.monotonic() + 240
        while not Path("/tmp/mps-release").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("MPS controller did not release the clients")
            time.sleep(0.2)
    finally:
        if pointer.value:
            call("cuMemFree_v2", pointer)
        call("cuDevicePrimaryCtxRelease_v2", device)
    print("CUDA MPS smoke passed", flush=True)


if __name__ == "__main__":
    main()
