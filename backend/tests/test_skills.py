import pytest

from app.domain.skills import ALIASES, is_named_product, known_canonical_skills, normalize_skill


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  K8s ", "kubernetes"),
        ("Problem-Solving", "problem solving"),
        ("problem   solving.", "problem solving"),
        ("Scikit-Learn", "scikit-learn"),
        ("Node.js", "node.js"),
        ("CI/CD", "ci/cd"),
        ("Rust", "rust"),
    ],
)
def test_normalize_skill(raw, expected):
    assert normalize_skill(raw) == expected


def test_alias_keys_are_normalized():
    # A key that normalize_skill can never produce would be dead.
    for key in ALIASES:
        assert key == key.lower().replace("-", " ").strip(), key


def test_canonical_names_are_stable():
    # Re-normalizing a canonical name must not change it, or groups split.
    for value in known_canonical_skills():
        assert normalize_skill(value) == value, value


def test_no_alias_chains():
    assert not set(ALIASES.values()) & set(ALIASES), "an alias value is also a key"


@pytest.mark.parametrize(
    ("skill", "named"),
    [
        ("python", True),
        ("power bi", True),
        ("node.js", True),
        ("search systems", False),
        ("ai coding tools", False),
        ("backend services", False),
        ("relational databases", False),
    ],
)
def test_is_named_product(skill, named):
    assert is_named_product(skill) is named
