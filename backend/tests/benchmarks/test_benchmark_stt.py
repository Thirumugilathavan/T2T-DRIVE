"""
Pytest integration wrapper for STT Benchmarking.
"""

from tests.benchmarks.benchmark_stt import test_benchmark_suite_execution

def test_stt_benchmark():
    test_benchmark_suite_execution()
