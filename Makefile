.PHONY: install test smoke exp01 exp02 exp03 exp04 profile fit synth cluster lint
PY ?= .venv/bin/python
install:
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"
test:
	$(PY) -m pytest
synth:
	$(PY) -m cao.cli carbon synth --days 30 --out data/processed/ci_synthetic.csv --store
smoke:
	$(PY) -m cao.cli profile --smoke --out results/migration_profile_smoke.csv
profile:
	$(PY) -m cao.cli profile --sizes 0.1,0.5,1,5,10,20 --repeats 3 --out results/migration_profile.csv --store
fit:
	$(PY) -m cao.cli fit results/migration_profile.csv --out config/migration_model.json
exp01:
	$(PY) experiments/exp01_payback_boundary.py
exp02:
	$(PY) experiments/exp02_policy_comparison.py
exp03:
	$(PY) experiments/exp03_forecast_sensitivity.py
exp04:
	$(PY) experiments/exp04_network_energy_sensitivity.py
cluster:
	bash deploy/k3d/create-cluster.sh carbon
lint:
	$(PY) -m ruff check cao tests experiments
