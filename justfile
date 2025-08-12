check:
    uv run ruff check
    uv run ruff format --check --preview
    uv run taplo fmt --check pyproject.toml
    uv run pytest
    uv run pyright src tests

fix:
    uv run ruff format --preview
    uv run ruff check --fix
    uv run taplo fmt pyproject.toml
