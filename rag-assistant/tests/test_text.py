from src.text import estimate_tokens, slugify, tokenize


def test_tokenize_preserves_technical_identifiers() -> None:
    tokens = tokenize("DPT 1.001 PID_LOAD_STATE_CONTROL")
    assert "dpt" in tokens
    assert "1.001" in tokens
    assert "pid_load_state_control" in tokens
    assert "load" in tokens
    assert "state" in tokens


def test_slugify_is_stable() -> None:
    assert slugify("03_07_02 Datapoint Types v02.02.01 AS") == (
        "03-07-02-datapoint-types-v02-02-01-as"
    )


def test_estimate_tokens_is_positive() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 40) == 10
