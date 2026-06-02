from pydantic import BaseModel
from tradingagents.agents.utils.structured import invoke_structured_obj


class _S(BaseModel):
    x: int


class _Good:
    def invoke(self, prompt):
        return _S(x=42)


class _Bad:
    def invoke(self, prompt):
        raise RuntimeError("boom")


def test_returns_object_on_success():
    out = invoke_structured_obj(_Good(), "p", _S(x=0), "T")
    assert out.x == 42


def test_returns_fallback_on_failure():
    out = invoke_structured_obj(_Bad(), "p", _S(x=7), "T")
    assert out.x == 7


def test_none_llm_returns_fallback():
    out = invoke_structured_obj(None, "p", _S(x=9), "T")
    assert out.x == 9
