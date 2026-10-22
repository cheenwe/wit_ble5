.PHONY: help install install-dev test lint format build check clean ci

help:
	@echo "make install-dev  - editable install with pytest/ruff"
	@echo "make test         - run unit tests"
	@echo "make lint         - ruff check"
	@echo "make build        - sdist + wheel"
	@echo "make check        - twine check dist"
	@echo "make ci           - lint + test (local CI)"
	@echo "make clean        - remove build artifacts"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

format:
	ruff check --fix .
	ruff format .

build:
	python -m build

check: build
	twine check dist/*

ci: lint test

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
