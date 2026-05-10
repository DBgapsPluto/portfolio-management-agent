import os
from tradingagents.observability.tracing import setup_tracing, traced


def test_setup_no_op_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    setup_tracing()  # must not raise


def test_traced_decorator_passes_through():
    @traced(name="test_fn")
    def add(a, b):
        return a + b
    assert add(2, 3) == 5
