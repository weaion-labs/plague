.PHONY: test integration doctor install

test:
	python -m pytest

integration:
	python -m pytest -m integration

doctor:
	python -m plague doctor

install:
	python -m pip install -e .
	python -m playwright install chromium
	python -m plague doctor --install
