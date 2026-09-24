# Day-1 install (Windows 11 team)

Everyone: Git, Python 3.11+ (python.org installer, tick "Add to PATH"), VS Code, clone the repo,
`python -m venv .venv`, `.venv\Scripts\activate`, `pip install -e ".[dev]"`, `pytest`.

## Member 1 — infrastructure + orchestrator (full environment)

1. `wsl --install -d Ubuntu` (PowerShell as admin, reboot).
2. Docker Desktop with WSL2 backend enabled for the Ubuntu distro.
3. Inside Ubuntu:
   ```bash
   sudo apt update && sudo apt install -y python3-venv python3-pip build-essential curl
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && sudo install kubectl /usr/local/bin/
   curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```
4. Clone the repo *inside* the WSL filesystem (`~/carbon-aware-orchestrator`, not `/mnt/c`).
5. `pip install -e ".[dev,k8s]"`, `bash deploy/k3d/create-cluster.sh`, `bash deploy/workloads/build.sh`.
6. Optional energy tooling: `sudo apt install powercap-utils` (RAPL works on Intel/AMD laptops in
   WSL2 only if `/sys/class/powercap` is exposed; otherwise use the power model + a wall-plug
   meter for calibration). Kepler needs a real Linux kernel with eBPF — treat as optional.
7. Optional: `sudo apt install criu` to explore kubelet checkpoint API (out of scope).

## Member 2 — ML + carbon forecasting (Windows)

`pip install -e ".[dev,forecast]" jupyter matplotlib`  (xgboost wheel installs fine on Windows).
Register for API keys: ENTSO-E (free, email support for the Web API token), EIA (instant),
Electricity Maps (free tier). Put them in `.env`.

## Member 3 — simulator + dashboard + evaluation (Windows)

`pip install -e ".[dev,dashboard]"`. Run `python experiments/exp02_policy_comparison.py`,
`streamlit run cao/dashboard/app.py`, `uvicorn cao.dashboard.api:app --reload`.

## Shared

- Branches: `feature/<name>`, PRs into `main`, `pytest` must pass.
- Data files in `data/processed/*.csv` are git-ignored; share via a cloud drive; commit only
  `data/sample/`.
- `config/migration_model.json` (fitted) **is** committed — it is a result.
