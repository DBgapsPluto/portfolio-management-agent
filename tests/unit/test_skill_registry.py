import pytest
from tradingagents.skills.registry import (
    register_skill, get_skill, list_skills, clear_registry, _reregister_all_skills,
)


@pytest.fixture(autouse=True)
def _re_register_skills_after_test():
    """Re-register all skills after each test that uses clear_registry."""
    yield
    # After the test, re-register all skills so later tests aren't broken
    _reregister_all_skills()


def test_register_and_lookup():
    clear_registry()

    @register_skill(name="test_double", category="test")
    def double(x: int) -> int:
        return x * 2

    fn = get_skill("test_double")
    assert fn(5) == 10


def test_unknown_skill_raises():
    clear_registry()
    with pytest.raises(KeyError, match="unknown_skill"):
        get_skill("unknown_skill")


def test_list_skills_by_category():
    clear_registry()

    @register_skill(name="a", category="macro")
    def a(): pass

    @register_skill(name="b", category="risk")
    def b(): pass

    @register_skill(name="c", category="macro")
    def c(): pass

    macro_skills = list_skills(category="macro")
    assert sorted(macro_skills) == ["a", "c"]


def test_duplicate_registration_raises():
    clear_registry()

    @register_skill(name="dup", category="x")
    def dup1(): pass

    with pytest.raises(ValueError, match="already registered"):
        @register_skill(name="dup", category="x")
        def dup2(): pass
