import pytest

from app.domain.skills import ALIASES, known_canonical_skills, normalize_skill


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
