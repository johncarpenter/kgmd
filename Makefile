.PHONY: install test lint format build clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v

lint:
	ruff check kgmd/ tests/

format:
	ruff format kgmd/ tests/
	ruff check --fix kgmd/ tests/

build:
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
