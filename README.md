# NAS Data Annotation Platform (`nas_annotation_automation`)

Central parent orchestration repository for the distributed NAS-backed computer vision data annotation platform.

---

## 🏗️ Architecture & Multi-Repository Overview

This ecosystem is organized into a parent orchestrator repository and two specialized sub-repositories integrated via Git submodules:

```
nas_annotation_automation/ (Main Orchestrator Repo)
├── admin_webpage/                 # [Submodule] Central Web Platform & REST API Controller
│   └── (https://github.com/Rushabh-Savla/admin_webpage)
├── annotator_app/                 # [Submodule] Annotator Desktop Workstation GUI Client
│   └── (https://github.com/Rushabh-Savla/annotator_app)
├── docker-compose.yml             # Full-stack production container orchestration
├── Dockerfile                     # Multi-service container specification
├── scripts/                       # Deployment, backup, NAS health & manager utilities
├── secrets/                       # Rclone & storage credential configurations
├── docs/                          # Architecture, schema, and workflow specifications
└── .github/workflows/             # Main system integration CI pipeline
```

---

## 📦 Sub-Repositories

| Sub-Repository | Role | Technology Stack | Repository Link |
| :--- | :--- | :--- | :--- |
| **`admin_webpage`** | Central Controller & Review Platform | FastAPI, Jinja2, PostgreSQL, SQLAlchemy, Alembic | [Rushabh-Savla/admin_webpage](https://github.com/Rushabh-Savla/admin_webpage) |
| **`annotator_app`** | Workstation GUI & Annotation Agent | Python Tkinter, HTTPX, X-AnyLabeling | [Rushabh-Savla/annotator_app](https://github.com/Rushabh-Savla/annotator_app) |

---

## 🚀 Cloning the Project with Submodules

To clone the main project including both sub-repositories on the active **`developing`** branch:

```bash
git clone --recurse-submodules -b developing https://github.com/Rushabh-Savla/nas_annotation_automation.git
cd nas_annotation_automation
```

If you already cloned without `--recurse-submodules`, initialize and pull submodules with:
```bash
git submodule update --init --recursive
```

To pull the latest updates across all submodules on the `developing` branch:
```bash
git submodule update --remote --merge
```

---

## 🐳 Quickstart: Docker Compose Deployment

The main repository orchestrates the entire server stack:
- **`postgres`:** Database running PostgreSQL 16
- **`migrate`:** Automated Alembic schema migrations
- **`controller`:** Central FastAPI web dashboard & REST API on port `8080`
- **`sync_worker`:** Background daemon for NAS staging, sync, and cataloging

### 1. Setup Environment Configuration

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials, NAS IP, and secrets
```

### 2. Build and Launch Stack

```bash
docker compose up -d --build
```

### 3. Verify Health

```bash
docker compose ps
curl http://localhost:8080/api/v1/health/liveness
```

Open the Central Dashboard in your browser: **`http://localhost:8080/dashboard`** (or your server IP, e.g. `http://192.168.1.103:8080/dashboard`).

---

## 🛠️ Management & Utility Scripts (`scripts/`)

- **`scripts/setup.sh` / `setup.ps1`:** Automated host dependencies setup.
- **`scripts/health.sh`:** Diagnoses NAS connectivity, database status, and disk space.
- **`scripts/backup.sh` & `restore.sh`:** PostgreSQL database snapshot backups and restoration.
- **`scripts/manager.py`:** Administrative CLI for cataloging and batch allocations.

---

## 🌿 Branching Strategy

- **`developing`:** Active development branch across the main repo and all sub-repositories. All new features, refactoring, and integration PRs target `developing`.
- **`main`:** Production-stable releases.