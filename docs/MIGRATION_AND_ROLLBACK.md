# Migration and Rollback Guide: Legacy POC to Centralized System

## 1. Overview & Guarantees

The legacy POC runs per-PC SQLite instances that independently allocate batches using `WORKER_INDEX` and `WORKER_COUNT`.
Under the new centralized multi-computer system, **PostgreSQL is the sole authority for global image ownership**.

### Critical Safety Rules:
- **Never delete or reset** existing local SQLite state, batches, backups, annotations, `config.env`, or local workspaces.
- **Never allow central and legacy systems to manage the same dataset concurrently**.
- **Source datasets on the NAS are strictly read-only**; assignment workspaces use staged copies.
- **Never fabricate empty JSONs** for unannotated images.

---

## 2. Pre-Migration Checklist

1. **Identify all machines running the legacy system**:
   - Locate every PC executing `desktop_app.py`, `start_annotation.sh`, or background systemd timers.
2. **Ensure existing batches are finalized or committed**:
   - If an annotator has an active local batch, allow them to finish annotating or run `bash scripts/sync_now.sh` to ensure all completed JSONs are uploaded and verified on NAS.
3. **Take a complete backup of legacy state**:
   ```bash
   # On each legacy PC:
   BACKUP_DIR="$HOME/legacy_annotation_backup_$(date +%Y%m%d_%H%M%S)"
   mkdir -p "$BACKUP_DIR"
   cp -a config.env "$BACKUP_DIR/"
   cp -a "$HOME/nas_annotation_workspace/state" "$BACKUP_DIR/"
   cp -a "$HOME/nas_annotation_workspace/backups" "$BACKUP_DIR/"
   echo "Legacy backup saved to $BACKUP_DIR"
   ```

---

## 3. Safe Migration Procedure

### Step 1: Stop Legacy Background Execution
On every client machine scheduled for migration, disable and stop the systemd timers to prevent them from waking up and modifying the dataset:
```bash
bash scripts/stop.sh
```
*Note*: `scripts/stop.sh` disables `batch-manager.timer` and `batch-cleanup.timer` and terminates any running oneshot jobs without deleting the workspace or SQLite database.

### Step 2: Deploy Centralized Server Platform
On the central Linux server:
1. Run `./scripts/setup.sh` to initialize environment and generate secrets.
2. Provide `secrets/rclone.conf` with NAS access credentials.
3. Start the services:
   ```bash
   docker compose up -d
   ```
4. Run migrations:
   ```bash
   docker compose run --rm migrate
   ```
5. Create the initial administrator:
   ```bash
   docker compose exec controller python -m controller.app.cli create-admin
   ```

### Step 3: Register and Scan the Dataset (Read-Only)
In the Master Web Dashboard (or via Admin CLI):
1. Navigate to **Datasets** $\rightarrow$ **Register Dataset**.
2. Enter the remote name (e.g. `annotation_nas`) and dataset path (e.g. `ai_data_collection/...`).
3. Click **Start Scan**.
4. The background worker inventories all files without downloading contents or modifying remote files.
5. Inspect the file counts (direct vs recursive images, JSONs, TXTs) and compare with the legacy catalog.

### Step 4: Pilot Test with a Small Separate Dataset
1. Create a small test dataset or test directory on the NAS (or mock storage).
2. Create two test annotators in the central dashboard.
3. Assign a small count (e.g., 20 images) to each annotator.
4. Have both annotators connect via the new Annotator Desktop Agent:
   - Download batch.
   - Annotate in XAnyLabeling.
   - Submit annotations.
   - Verify upload and server confirmation.
5. Verify that neither annotator received the same image and that active claims released upon completion.

### Step 5: Cutover Production Dataset
1. Confirm legacy systemd timers on all annotator PCs are stopped.
2. Perform a fresh scan of the production dataset in the central system to obtain the authoritative snapshot.
3. Create assignments for annotators using the Master Dashboard.
4. Annotators start work using the new desktop agent.

---

## 4. Rollback Procedure

If unexpected issues arise during pilot or initial production:

1. **Stop Central Work**:
   - In the Master Web Dashboard, pause or cancel active assignments. This prevents new batch downloads.
   - Stop central services:
     ```bash
     docker compose down
     ```
2. **Preserve Completed Annotations**:
   - All completed annotations uploaded during central operation remain safely in `<ANNOTATION_WORKSPACE_ROOT>/` or alongside source images.
   - Run a PostgreSQL logical backup:
     ```bash
     docker compose exec postgres pg_dump -U postgres annotation_db > rollback_backup.sql
     ```
3. **Re-enable Legacy Mode on Client PCs**:
   - On each client PC, legacy `config.env` and SQLite state (`$HOME/nas_annotation_workspace/state/state.db`) remain completely intact.
   - Re-enable the legacy timers if desired:
     ```bash
     bash scripts/install.sh
     ```
   - Launch legacy desktop GUI or scripts:
     ```bash
     ./run_gui.sh
     ```
4. **Post-Rollback Audit**:
   - Compare remote files to verify no files were lost or corrupted.

