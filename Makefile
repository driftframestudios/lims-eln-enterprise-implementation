.PHONY: validate test build

validate:
	python3 scripts/validate_implementation.py
	python3 -m ruff check src tests scripts

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

build:
	python3 -m build
