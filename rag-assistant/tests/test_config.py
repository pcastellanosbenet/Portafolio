from pathlib import Path

from src.config import Settings


def test_effective_qdrant_path_follows_artifacts_directory(tmp_path: Path) -> None:
    settings = Settings(artifacts_dir=tmp_path, corpus_dir=tmp_path)

    assert settings.effective_qdrant_path == tmp_path / "qdrant"


def test_explicit_qdrant_path_takes_precedence(tmp_path: Path) -> None:
    custom = tmp_path / "custom-qdrant"
    settings = Settings(
        artifacts_dir=tmp_path,
        corpus_dir=tmp_path,
        qdrant_path=custom,
    )

    assert settings.effective_qdrant_path == custom


def test_explicit_default_qdrant_path_is_respected(tmp_path: Path) -> None:
    settings = Settings(
        artifacts_dir=tmp_path,
        corpus_dir=tmp_path,
        qdrant_path=Path("artifacts/qdrant"),
    )

    assert settings.effective_qdrant_path == Path("artifacts/qdrant")
