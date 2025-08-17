[private]
default:
   @just --list

# Run taplo, ruff, pytest, and pyright in check mode
check:
    uv run taplo fmt --check pyproject.toml
    uv run ruff format --check --preview
    uv run ruff check
    uv run pytest
    uv run pyright src tests

# Run taplo and ruff in fix mode
fix:
    uv run taplo fmt pyproject.toml
    uv run ruff format --preview
    uv run ruff check --fix
