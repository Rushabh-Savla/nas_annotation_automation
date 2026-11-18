# Unified NAS Data Annotation Platform

## 1. System Architecture

```text
                  +----------------------------------------------+
                  |               Remote NAS / Storage           |
                  |     (Canonical Datasets & Sidecar Outputs)    |
                  +----------------------------------------------+
                                         ▲
                                         │  (Rclone SFTP/SMB)
                                         ▼
+---------------------------------------------------------------------------------+
|                       CENTRAL SERVER (admin-web)                                  |
|                                                                                 |
|   +-----------------------+                    +----------------------------+   |
|   |  FastAPI Controller   |                    |        Sync Worker         |   |
|   |  - Web Dashboard      |   (Job Queue)      |  - Catalog scans           |   |
|   |  - Auth & Admin APIs  | ─────────────────► |  - Staging preparation    |   |
|   |  - Assignment APIs    |                    |  - Output verification     |   |
|   +-----------┬-----------+                    |  - NAS upload worker       |   |
|               │                                +─────────────┬──────────────+   |
|               │                                              │                  |
|               ▼                                              │                  |
|   +----------------------------------------------------------▼--------------+   |
|   |                      PostgreSQL 16 Database                             |   |
|   |   - Users, Roles (ADMIN, MANAGER, ANNOTATOR) & Devices                  |   |
|   |   - Dataset catalogs (directories, files, hashes, versions)             |   |
|   |   - Active Image Claims (Atomic Single-Owner Leases)                    |   |
|   |   - Submissions, Approval workflows, and Audit event logs               |   |
|   +-------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------+
                                         ▲
                                         │  REST APIs & Heartbeats
                                         │  (Port :8080)
                                         ▼
+---------------------------------------------------------------------------------+
|                    ANNOTATOR WORKSTATIONS (local-app)                           |
|                                                                                 |
|   +-------------------------------------------------------------------------+   |
|   |                      Desktop GUI (desktop_app.py)                       |   |
|   |   - Annotator login & live server sync                                  |   |
|   |   - Claim next batch / active assignments                               |   |
|   |   - Launches X-AnyLabeling on local SSD workspace                       |   |
|   |   - JSON schema validation & batch submission                           |   |
|   |   - SQLite local agent cache (offline-resilient)                        |   |
|   +-------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------+
```

---

## 2. Repository Structure

This repository is organized as a unified monorepo containing two Git submodules:

```text
nas_annotation_automation/
├── README.md               # Main unified platform documentation (this file)
├── .gitmodules             # Submodule definitions for admin-web and local-app
│
├── admin-web/                # [Submodule] Central server & sync backend
│   ├── .env.example        # Server configuration template
│   ├── docker-compose.yml  # PostgreSQL, Alembic, Controller, Worker orchestration
│   ├── Dockerfile          # Python 3.12 application container
│   ├── controller/         # FastAPI web application, API routers, and Dashboard
│   ├── sync_worker/        # Queue consumer & Rclone NAS transfer service
│   ├── alembic/            # Database schema migration revisions
│   ├── scripts/            # CLI management and health check utilities
│   └── README.md           # Detailed server deployment & API documentation
│
└── local-app/              # [Submodule] Annotator workstation desktop client
    ├── .env.example        # Workstation configuration template
    ├── desktop_app.py      # Tkinter desktop GUI for annotators
    ├── annotator_agent/    # Client API client, token handling, local SQLite cache
    ├── run_gui.sh          # 1-Click GUI launcher for Linux & macOS
    ├── run_gui.bat         # 1-Click GUI launcher for Windows
    ├── requirements_agent.txt # Workstation dependencies (httpx, xanylabeling, etc.)
    └── README.md           # Detailed workstation setup & usage documentation
```

---

## 3. Cloning the Repository

Because this repository contains Git submodules, clone it with the `--recurse-submodules` flag:

```bash
git clone --recurse-submodules https://github.com/Rushabh-Savla/nas_annotation_automation.git
cd nas-data-annotation-platform
```

> If you already cloned the repository without `--recurse-submodules`, initialize and fetch submodules with:
> ```bash
> git submodule update --init --recursive
> ```

---

## 4. Quickstart: Central Server (`web-app`)

Deploy the central controller, database, and background worker on your server or primary host machine.

### 4.1 Configure `.env`
Navigate to `web-app` and create the environment configuration:
```bash
cd admin-web
cp .env.example .env
```

Generate secure secrets and update your `.env`:

1. **`APP_SECRET_KEY` (64-character random key):**
   ```bash
   openssl rand -hex 32
   ```
2. **`POSTGRES_PASSWORD` & `DATABASE_URL`:**
   ```bash
   openssl rand -hex 16
   ```
   Set both `POSTGRES_PASSWORD` and the password in `DATABASE_URL` to match:
   ```dotenv
   POSTGRES_PASSWORD=your_generated_hex_password
   DATABASE_URL=postgresql://annotation_user:your_generated_hex_password@postgres:5432/annotation_db
   ```
3. **`BOOTSTRAP_ADMIN_TOKEN`:**
   ```bash
   openssl rand -hex 16
   ```
4. **NAS Storage Details:**
   Configure your SFTP/SMB storage target:
   ```dotenv
   NAS_STORAGE_TYPE=sftp
   NAS_HOST=192.168.1.100
   NAS_PORT=22
   NAS_USER=nas_user
   NAS_PASSWORD=nas_password
   NAS_ROOT_PATH=/data
   ```

### 4.2 Start Services
```bash
mkdir -p secrets
docker compose up -d
```

Verify all containers are healthy:
```bash
docker compose ps
```
Services running:
- `annotation_postgres`: Database (port `127.0.0.1:54321`)
- `annotation_migrate`: Runs database migrations (`alembic upgrade head`)
- `annotation_controller`: FastAPI server (port `8080`)
- `annotation_sync_worker`: Background queue processor

### 4.3 Create the First Admin Account
```bash
docker compose exec controller python -m controller.app.cli create-admin --username admin --password 'Admin@123'
```

Access the web interface:
- **Web Dashboard:** [http://localhost:8080/dashboard](http://localhost:8080/dashboard)
- **Interactive API Docs:** [http://localhost:8080/docs](http://localhost:8080/docs)

---

## 5. Rclone Setup & Remote NAS Configuration Guide

The central platform and background worker use **Rclone** to index remote dataset trees, transfer images, and sync annotations back to the NAS without mounting unstable network filesystems.

### 5.1 Install Rclone (Host Machine)
```bash
sudo apt update
sudo apt install rclone
```

### 5.2 One-Time Interactive Rclone Configuration
Run the Rclone configuration wizard on the host machine:
```bash
rclone config
```

Follow the step-by-step setup:
1. `n/s/q>`: Type `n` (New remote)
2. `name>`: Type `annotation_nas` *(Must match `DEFAULT_REMOTE_NAME` in `.env`)*
3. `Storage>`: Type `sftp` *(for SFTP/SSH storage)*
4. `host>`: Enter your NAS IP address or hostname (e.g. `192.168.1.100`)
5. `user>`: Enter your NAS SSH username (e.g. `Annotation` or `nas_user`)
6. `port>`: Press Enter to use the default port `22` (or custom port)
7. `y/g/n>`: Type `y` (type in your password manually)
8. `SSH password>`: Enter your NAS password and confirm
9. `key_pem>`: Press Enter (leave blank)
10. `key_file>`: Press Enter (leave blank unless using private SSH key)
11. `key_file_pass>`: Type `n`
12. `pubkey_file>`: Press Enter (leave blank)
13. `key_use_agent>`: Press Enter (default `false`)
14. `use_insecure_cipher>`: Press Enter (default `false`)
15. `disable_hashcheck>`: Press Enter (default `false`)
16. `Edit advanced config? (y/n)>`: Type `n`
17. `Keep this "annotation_nas" remote? (y/e/d)>`: Type `y`
18. `e/n/d/r/c/s/q>`: Type `q` to quit config

### 5.3 Verify Remote NAS Connectivity
Test that the NAS is reachable and view existing directories:
```bash
rclone lsd annotation_nas:
```
*To verify dataset storage subfolders (e.g. `/data` or `/ai_data_collection`):*
```bash
rclone lsd annotation_nas:/data
```

### 5.4 Linking with Docker Central Platform (`web-app`)
You can supply Rclone credentials to the central Docker platform in one of two ways:
- **Automatic via `.env` (Recommended):** Set `NAS_STORAGE_TYPE=sftp`, `NAS_HOST`, `NAS_PORT`, `NAS_USER`, and `NAS_PASSWORD` in `admin-web/.env`. On container startup, the controller will automatically generate and obscure passwords into `admin-web/secrets/rclone.conf` with `600` permissions.
- **Manual Copy from Host:** Copy your host's existing `rclone.conf` into the secrets folder:
  ```bash
  mkdir -p admin-web/secrets
  cp ~/.config/rclone/rclone.conf admin-web/secrets/rclone.conf
  chmod 600 admin-web/secrets/rclone.conf
  ```

---

## 6. Quickstart: Annotator Workstation (`local-app`)

Install and run the desktop client on each annotator's PC.

### 6.1 Set Up Python Environment

#### Linux / macOS
```bash
cd local-app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements_agent.txt
```

#### Windows
```cmd
cd local-app
py -m venv .venv
.venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements_agent.txt
```

### 6.2 Configure `.env`
```bash
cp .env.example .env
```
Edit `.env` for your local workstation:
```dotenv
SERVER_URL="http://<SERVER_IP>:8080"
ROOT="$HOME/nas_annotation_workspace"
```

> **Important (Linux Path Permissions):**
> Always set `ROOT` inside your own user home directory (e.g. `$HOME/nas_annotation_workspace` or `/home/<username>/nas_annotation_workspace`). Never use `/home/annotator/...` unless your Linux user account is named `annotator`, otherwise you will encounter `PermissionError: [Errno 13] Permission denied`.

### 6.3 Launch the Desktop GUI
- **Linux / macOS:**
  ```bash
  ./run_gui.sh
  ```
- **Windows:**
  ```cmd
  run_gui.bat
  ```

Log in using the annotator credentials created in the central dashboard.

---

## 7. End-to-End Workflow

```mermaid
flowchart TD
    A["1. Admin Registers Dataset"] --> B["2. Worker Runs Catalog Scan via Rclone"]
    B --> C["3. Image Files & Tree Indexed in PostgreSQL"]
    C --> D["4. Manager Creates Assignment Batch"]
    D --> E["5. Annotator Claims Batch in Desktop GUI"]
    E --> F["6. Images Downloaded to Local SSD & Atomic Lease Granted"]
    F --> G["7. Annotator Labels in X-AnyLabeling"]
    G --> H["8. Desktop App Validates JSON Syntax & Schema"]
    H --> I["9. Annotations Submitted to Central Server"]
    I --> J["10. Worker Uploads Verified Output to NAS"]
    J --> K["11. Lease Released & Audit Log Recorded"]
```

1. **Register Dataset:** In the web dashboard, an admin or manager registers a dataset path on the NAS.
2. **Catalog Indexing:** The `sync_worker` scans the remote path and indexes eligible image files into PostgreSQL.
3. **Batch Assignment:** A manager creates an assignment for an annotator with a specified batch size.
4. **Batch Claiming:** The annotator opens the desktop GUI and clicks **Claim Next Batch**.
5. **Atomic Single-Ownership:** PostgreSQL acquires an atomic claim in `active_image_claims`. No other annotator can claim or overwrite these images while leased.
6. **Annotation:** Images are staged on local SSD storage, and the app opens [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) for rapid labeling.
7. **Validation & Sync:** Completed JSON annotations are validated for syntax and schema compliance, uploaded to the central server, and synchronized to the NAS by the sync worker.
8. **Review & Audit:** Managers review completion metrics and submission histories with full audit tracking.

---

## 8. Common Troubleshooting

| Issue / Symptom | Root Cause | Solution |
| :--- | :--- | :--- |
| **`annotation_migrate` exits with code 1: `password authentication failed`** | Docker volume `postgres_data` already exists from an earlier run with a different password. | In `web-app`: Run `docker compose exec postgres psql -U annotation_user -d annotation_db -c "ALTER USER annotation_user WITH PASSWORD '<YOUR_PASSWORD>';"` then restart, OR run `docker compose down -v && docker compose up -d` for a clean reset. |
| **`PermissionError: [Errno 13] Permission denied: '/home/annotator'`** | `local-app/.env` is set to `/home/annotator`, but current Linux user is different. | In `local-app/.env`: Change `ROOT` to `$HOME/nas_annotation_workspace` or `/home/<your_user>/nas_annotation_workspace`. |
| **`Could not resolve host: <NAS_HOST>`** | Incorrect network configuration or VPN required to reach NAS storage. | Verify NAS IP/hostname and ensure Rclone credentials in `.env` are accurate. |
| **Submodule folders appear empty after clone** | Cloned without `--recurse-submodules`. | Run `git submodule update --init --recursive` in the root repository. |

---

## 9. Security Best Practices

- **Never Commit Secrets:** `.env` and `secrets/` files are explicitly excluded in `.gitignore` across all submodules. Never push passwords, tokens, or NAS keys to version control.
- **Loopback Postgres Binding:** The PostgreSQL container is bound to `127.0.0.1:54321` on the host, preventing external access from the network.
- **Least-Privilege NAS Access:** Grant the sync worker read-only permissions on canonical dataset roots and write access only to the dedicated annotation workspaces folder.

---

## 10. Submodule Repositories

- Central Server Repository: [https://github.com/Rushabh-Savla/admin-web](https://github.com/Rushabh-Savla/admin-web)
- Annotator Client Repository: [https://github.com/Rushabh-Savla/local-app](https://github.com/Rushabh-Savla/local-app)

