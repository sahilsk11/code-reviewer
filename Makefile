.PHONY: checks lint test

checks: lint test

lint:
	python -m ruff check .
	python -m pyright

test:
	python -m pytest
