# System Architecture: Centralized Multi-Computer NAS Annotation Platform

## 1. Overview & High-Level Topology

The Centralized Multi-Computer NAS Annotation Platform transitions the legacy per-PC SQLite proof-of-concept into a resilient, scalable, centrally managed system.

```
                      +---------------------------------------+
                      |         CENTRAL LINUX SERVER          |
                      |            (Docker Compose)           |
                      |                                       |
                      |  +---------------------------------+  |
                      |  |     HTTPS / Reverse Proxy       |  |
                      |  |   (Caddy / Corporate Gateway)   |  |
                      |  +----------------+----------------+  |
                      |                   |                   |
                      |                   v                   |
                      |  +---------------------------------+  |
                      |  |        Controller (FastAPI)     |  |
                      |  |   - REST API (/api/v1)          |  |
                      |  |   - Admin Web Dashboard (Jinja) |  |
                      |  |   - Auth / RBAC / Leases        |  |
                      |  +--------+---------------+--------+  |
                      |           |               |           |
                      |    (Internal Net)   (Internal Net)    |
                      |           v               v           |
                      |  +-------------+  +----------------+  |
                      |  | PostgreSQL  |  |  Sync Worker   |  |
                      |  | (Authorita- |  | (Rclone Staging|  |
                      |  | tive Store) |  |  Upload/Verify)|  |
                      |  +-------------+  +-------+--------+  |
                      +---------------------------|-----------+
                                                  |
           +--------------------------------------+--------------------------------------+
           | (Authenticated HTTPS REST API)       | (Rclone SFTP/SMB/NFS - Server Only) |
           v                                      v                                      v
+-----------------------+              +--------------------+                 +--------------------+
| Annotator PC 1        |              | Canonical NAS      |                 | NAS Assignment     |
| - Annotator Agent     |              | Dataset (READ-ONLY)|                 | Workspace          |
| - Local SSD Cache     |              |                    |                 | (STAGED COPIES)    |
| - XAnyLabeling        |              +--------------------+                 +--------------------+
+-----------------------+
| Annotator PC 2..N     |
+-----------------------+
```

## 2. Containerized Services (Docker Compose)

The backend runs as four distinct services on a single Linux host using Docker Compose:

1. **`controller`**:
   - FastAPI application serving both `/api/v1` and the server-rendered responsive administration web UI.
   - Enforces RBAC (`ADMIN`, `MANAGER`, `ANNOTATOR`), authentication (Argon2id password hashing, secure session and bearer tokens), and rate limiting.
   - Executes atomic transactions for assignment reservations.
   - Runs as non-root user (`appuser`, UID 1000).
   - Only exposed to internal Docker network or reverse proxy port (default `8000`).

2. **`postgres`**:
   - Official pinned PostgreSQL image (e.g., `postgres:16-alpine`).
   - Attached to a named persistent Docker volume (`postgres_data`).
   - Runs with internal container health checks (`pg_isready`).
   - Placed on a private internal Docker bridge network (`backend_net`).
   - **Never publicly exposed to the host network or Internet**.

3. **`sync_worker`**:
   - Dedicated Python worker process sharing the backend codebase.
   - Claims background tasks from PostgreSQL using atomic `SELECT ... FOR UPDATE SKIP LOCKED`.
   - Responsibilities:
     - Remote NAS inventory and metadata cataloging (using Rclone).
     - Copying and staging assigned images into dedicated per-annotator assignment directories on the NAS.
     - Verifying staged file counts, relative paths, sizes, and fingerprints before marking assignments `READY`.
     - Validating submitted annotation JSON payloads.
     - Performing controlled uploads of verified annotations to designated targets and running remote verification.
   - Has read-only mount to `secrets/rclone.conf`.

4. **`migrate`**:
   - Ephemeral one-shot service running `alembic upgrade head`.
   - Starts before `controller` and `sync_worker` to ensure all schema migrations and indexes are active.

5. **Reverse Proxy (Optional / Documented Integration)**:
   - Caddy or corporate Nginx/Traefik providing TLS termination, HTTP/2, strict security headers, and reverse proxying to `controller:8000`.

## 3. Security Boundaries & Threat Modeling

| Boundary | Policy | Implementation |
|---|---|---|
| **Annotator PC $\leftrightarrow$ Server** | Authenticated HTTPS REST only | JWT / Bearer tokens, Argon2id passwords, strict TLS, rate-limited auth endpoints. |
| **Annotator PC $\leftrightarrow$ PostgreSQL** | Strictly Forbidden | Database has no exposed host port; lives solely in private Docker network. |
| **Annotator PC $\leftrightarrow$ NAS** | Direct write strictly forbidden | Annotator agent receives images and manifests exclusively via Controller API; NAS credentials never distributed to client PCs. |
| **Server $\leftrightarrow$ NAS Source Datasets** | Read-Only | Canonical datasets are cataloged and read, never modified or moved. |
| **Server $\leftrightarrow$ NAS Workspaces** | Controlled Write | Only `sync_worker` stages image copies and writes annotations using dedicated Rclone parameters. |
| **Client Work Ownership** | Fencing & Leases | Every assignment has an ownership generation and lease. Reassigned or stale workers cannot submit or overwrite work. |
| **File System Injection** | Traversal Protection | All paths validated against directory traversal (`..`, leading slashes, symlink escapes, drive letters). |

## 4. End-to-End Data Flows

### A. Catalog & Inventory Flow
1. Manager initiates a catalog scan for a registered dataset path via Web UI or API.
2. `sync_worker` claims the scan job and executes an Rclone listing command (`rclone lsf` / `lsjson`) in a bounded, streaming manner.
3. Classifies all discovered files into categories (Images: JPG, JPEG, PNG, BMP, WEBP, TIF, TIFF; Sidecars: JSON, TXT; Other).
4. Normalizes relative paths, records file sizes, modification timestamps, and hashes where supported.
5. Generates an immutable `catalog_version` snapshot fingerprint.

### B. Count-Based Atomic Assignment Flow
1. Manager selects dataset, folder scope (direct-only or recursive), target annotator, and exact count $N$.
2. Controller opens a PostgreSQL transaction:
   - Queries eligible unassigned images in deterministic order.
   - Locks candidate rows with `FOR UPDATE SKIP LOCKED`.
   - Checks that count equals $N$; if fewer than $N$ are available, aborts with a complete rollback.
   - Inserts `assignment`, `assignment_items`, and `active_image_claims`.
3. Commits transaction and enqueues `PREPARE_ASSIGNMENT` sync job.

### C. Workspace Staging Flow
1. `sync_worker` claims `PREPARE_ASSIGNMENT`.
2. Creates destination folder `<WORKSPACE_ROOT>/<annotator_id>/assignment_<id>/`.
3. Copies selected images into `images/` using Rclone with subprocess argument arrays (never shell interpolation).
4. Verifies remote file existence, sizes, and counts. Writes `manifest.json`.
5. Updates assignment status from `PREPARING` to `READY`.

### D. Desktop Agent Annotation Flow
1. Annotator logs into Desktop Agent; agent requests active assignments.
2. Agent requests authorized batch manifest (default 100 images) for its active assignment.
3. Downloads batch images to local SSD workspace (`<ROOT>/current/`).
4. Launches XAnyLabeling on local directory.
5. Monitors saved JSON files, verifying stability and valid syntax.
6. Submits completed annotations via authenticated REST API with SHA-256 hash and fencing token.
7. Server validates schema and records submission; local batch is preserved until upload verification is confirmed by the server.

### E. Background & Unannotated Images
1. Batches may contain intentional negative/background images.
2. An image without an annotation is explicitly declared as a background image.
3. Manager reviews or auto-accepts based on dataset policy; no empty or placeholder JSON files are ever fabricated.

