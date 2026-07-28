.PHONY: validate test

validate:
	python3 scripts/validate_repository.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

