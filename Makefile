# One-command reproduction. `make` = fetch live data and rebuild everything.
PY ?= python3

.PHONY: all install run offline model test serve

all: install run

install:
	$(PY) -m pip install -q -r requirements.txt

run:            ## fetch live public data, rebuild charts, dashboard, EVIDENCE.md, model
	$(PY) -m near_thesis run

offline:        ## rebuild everything from the committed snapshot (no network)
	$(PY) -m near_thesis run --offline

model:          ## re-run only the valuation model (edit config/assumptions.yaml first)
	$(PY) -m near_thesis model

test:
	$(PY) -m pytest -q

serve:          ## view the dashboard locally at http://localhost:8000
	$(PY) -m http.server 8000 -d docs
