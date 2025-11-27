.PHONY: install test run clean

VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

install: $(VENV)/bin/activate

clean:
	rm -rf $(VENV)
	rm -rf __pycache__

# The following two targets can only run with a valid .env file
test: install
	$(PYTHON) sync.py --once

run: install
	$(PYTHON) sync.py

run-once: install
	$(PYTHON) sync.py --once
