.PHONY: validate implementation-validation test

validate:
	python3 scripts/validate_repository.py

implementation-validation:
	python3 scripts/validate_implementation.py
	python3 scripts/build_package_archive.py /tmp/lims_eln_enterprise_implementation-0.3.1-py3-none-any.whl

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
