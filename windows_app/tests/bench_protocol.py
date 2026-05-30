"""Microbenchmarks for the BLE protocol builders/parsers.

Run with:
    pytest -m benchmark windows_app/tests/bench_protocol.py

Default `pytest` invocations skip benchmarks via the `addopts = "-m 'not
benchmark'"` deselection in `pyproject.toml`. The numbers are not pass/fail gates; they
exist so a future regression in the hot-path serialization can be spotted
by comparing benchmark runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pytest_benchmark",
    reason="install dev requirements (`pip install -r windows_app/requirements-dev.txt`) to enable benchmarks",
)

sys.path.insert(0, str(Path(__file__).parent.parent))

import ble_protocol


pytestmark = pytest.mark.benchmark


@pytest.fixture
def palette():
    return [(i * 16, 255 - i * 16, i * 8, 50) for i in range(16)]


def test_bench_keep_alive(benchmark):
    benchmark(ble_protocol.keep_alive)


def test_bench_lock_device(benchmark):
    benchmark(ble_protocol.lock_device, True)


def test_bench_change_profile(benchmark):
    benchmark(ble_protocol.change_profile, 1, "Default")


def test_bench_sync_profiles(benchmark):
    profiles = {i: f"Profile {i}" for i in range(1, 11)}
    benchmark(ble_protocol.sync_profiles, profiles)


def test_bench_set_rgb_key(benchmark):
    benchmark(ble_protocol.set_rgb_key, 5, 255, 0, 0, 50)


def test_bench_set_all_rgb_keys(benchmark, palette):
    benchmark(ble_protocol.set_all_rgb_keys, palette)


def test_bench_hello(benchmark):
    benchmark(ble_protocol.hello, "0.2.4")


def test_bench_parse_keep_alive(benchmark):
    packet = ble_protocol.keep_alive()
    benchmark(ble_protocol.BLEPacket.parse, packet)


def test_bench_parse_device_telemetry(benchmark):
    payload = (
        bytes([1, 5]) + b"1.2.4"
        + (5000).to_bytes(4, "big")
        + bytes([1])
        + (200000).to_bytes(4, "big")
        + (0).to_bytes(2, "big")
    )
    benchmark(ble_protocol.parse_device_telemetry, payload)
