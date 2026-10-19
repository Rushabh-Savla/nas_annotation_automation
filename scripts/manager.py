#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IMAGE_EXT = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"
}


def readcfg(path):
    data = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        value = os.path.expandvars(os.path.expanduser(value))
        data[key] = value
    return data


def integer(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def number(data, key, default):
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def paths(cfg):
    root = Path(cfg["ROOT"]).expanduser().resolve()
    return {
        "root": root,
        "state": root / "state",
        "db": root / "state" / "state.db",
        "batches": root / "batches",
        "backups": root / "backups",
        "logs": root / "logs",
        "tmp": root / "tmp",
        "current": root / "current",
        "pid": root / "state" / "app.pid",
        "lock": root / "state" / "manager.lock",
    }


def dbopen(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS catalog (
            seq INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL DEFAULT 0,
            ann TEXT NOT NULL,
            annexists INTEGER NOT NULL DEFAULT 0,
            assigned INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS remote_files (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            expected INTEGER NOT NULL,
            created INTEGER NOT NULL,
            complete_at INTEGER NOT NULL DEFAULT 0,
            uploaded_at INTEGER NOT NULL DEFAULT 0,
            cleaned_at INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            next_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS items (
            batch INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            image TEXT NOT NULL,
            ann TEXT NOT NULL,
            annexists INTEGER NOT NULL DEFAULT 0,
            basesize INTEGER,
            basetime INTEGER,
            basehash TEXT,
            localsize INTEGER,
            localtime INTEGER,
            localhash TEXT,
            backhash TEXT,
            state TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT,
            PRIMARY KEY(batch, seq),
            FOREIGN KEY(batch) REFERENCES batches(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_catalog_assigned ON catalog(assigned, seq)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_items_state ON items(batch, state)")
    db.commit()
    return db


def meta(db, key, value=None):
    if value is None:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    db.commit()
    return str(value)


def now():
    return int(time.time())


def interval(value):
    text = str(value or "1m").strip().lower()
    m = re.match(r"^(\d+)\s*(s|m|h|d)$", text)
    if not m:
        return 60
    base = int(m.group(1))
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
    return max(1, base * mult)


def rel(path, root):
    return Path(path).relative_to(root).as_posix()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as src:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def validjson(path):
    try:
        with Path(path).open("r", encoding="utf-8-sig") as src:
            json.load(src)
        return True
    except (OSError, ValueError, TypeError):
        return False


def envcfg():
    conf = Path(__file__).resolve().parents[1] / "config.env"
    if not conf.exists():
        raise SystemExit(f"Missing configuration: {conf}")
    cfg = readcfg(conf)
    cfg["CONF"] = str(conf)
    return cfg


def cmdrun(cmd, timeout=None, input=None):
    try:
        proc = subprocess.run(
            cmd,
            input=input,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, text + "\nTIMEOUT"


def flags(cfg):
    out = [
        "--transfers", cfg.get("TRANSFERS", "1"),
        "--checkers", cfg.get("CHECKERS", "1"),
        "--sftp-concurrency", cfg.get("SFTP_CONCURRENCY", "1"),
        "--retries", cfg.get("RETRIES", "3"),
        "--low-level-retries", cfg.get("LOW_RETRIES", "3"),
        "--timeout", cfg.get("TIMEOUT", "30s"),
        "--contimeout", cfg.get("CONNECT_TIMEOUT", "10s"),
        "--stats", "1m",
        "--stats-one-line",
        "--log-level", "NOTICE",
    ]
    rate = cfg.get("BANDWIDTH", "").strip()
    if rate:
        out += ["--bwlimit", rate]
    return out


def remote(cfg, path=""):
    base = cfg["DATASET"].strip("/")
    if path:
        return f"{cfg['REMOTE']}:{base}/{path.lstrip('/')}"
    return f"{cfg['REMOTE']}:{base}"


def excludes(cfg):
    out = []
    for item in cfg.get("EXCLUDE", "").split(","):
        item = item.strip()
        if item:
            out += ["--exclude", item]
    return out


def images(cfg):
    values = cfg.get("IMAGE_EXTENSIONS", ",".join(x.lstrip(".") for x in IMAGE_EXT)).split(",")
    return {"." + x.lower().lstrip(".") for x in values if x.strip()}


def ensurepaths(cfg):
    out = paths(cfg)
    for key in ("state", "batches", "backups", "logs", "tmp"):
        out[key].mkdir(parents=True, exist_ok=True)
    out["root"].mkdir(parents=True, exist_ok=True)
    return out


def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def log(cfg, name, text):
    out = paths(cfg)["logs"]
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"{name}-{stamp}.log").write_text(text or "", encoding="utf-8")


def notify(cfg, title, text):
    if cfg.get("NOTIFY", "1") != "1":
        return
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def appactive(ppath):
    try:
        pid = int(ppath.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        try:
            ppath.unlink()
        except OSError:
            pass
        return False


def current(db):
    row = db.execute("SELECT value FROM meta WHERE key='current_batch'").fetchone()
    return int(row[0]) if row else None


def setcurrent(db, value):
    if value is None:
        db.execute("DELETE FROM meta WHERE key='current_batch'")
    else:
        db.execute("INSERT INTO meta(key,value) VALUES('current_batch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(value),))
    db.commit()


def configkey(cfg):
    keys = (
        "REMOTE", "DATASET", "WORKER_INDEX", "WORKER_COUNT",
        "IMAGE_EXTENSIONS", "EXCLUDE",
    )
    return "|".join(f"{key}={cfg.get(key, '')}" for key in keys)


def guardconfig(cfg, db):
    old = meta(db, "config_key")
    new = configkey(cfg)
    if old == new:
        return
    if current(db) is not None:
        raise RuntimeError("Dataset-related config changed while a batch is active. Finish or clear the current batch first.")
    meta(db, "config_key", new)
    db.execute("DELETE FROM remote_files")
    db.execute("DELETE FROM catalog")
    db.execute("DELETE FROM meta WHERE key IN ('catalog_created','done')")
    db.commit()


def due(db, cfg):
    last = meta(db, "last_manager_run")
    if last is None:
        return True
    return now() - int(last) >= interval(cfg.get("SYNC_INTERVAL", "1m"))


def markrun(db):
    meta(db, "last_manager_run", now())


def symlink(path, target):
    temp = path.with_name(path.name + ".new")
    try:
        if temp.exists() or temp.is_symlink():
            if temp.is_dir() and not temp.is_symlink():
                shutil.rmtree(temp)
            else:
                temp.unlink()
        temp.symlink_to(target, target_is_directory=True)
        if path.exists() or path.is_symlink():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        os.replace(temp, path)
    except Exception:
        try:
            if temp.exists() or temp.is_symlink():
                if temp.is_dir() and not temp.is_symlink():
                    shutil.rmtree(temp)
                else:
                    temp.unlink()
        except OSError:
            pass
        raise


def annpath(image):
    path = Path(image)
    return path.with_suffix(".json").as_posix()


def catalog(cfg, db):
    if current(db) is not None:
        raise RuntimeError("Cannot rebuild catalog while a batch is active")
    rbin = cfg.get("RCLONE_BIN", "rclone")
    args = [rbin, "lsf", remote(cfg), "--recursive", "--files-only", "--format", "ps", "--separator", "\t"]
    args += excludes(cfg)
    code, text = cmdrun(args, timeout=3600)
    log(cfg, "catalog", text)
    if code != 0:
        raise RuntimeError("Remote catalog listing failed")

    exts = images(cfg)
    db.execute("DELETE FROM remote_files")
    db.execute("DELETE FROM catalog")
    db.commit()

    count = 0
    with db:
        for line in text.splitlines():
            if not line or "\t" not in line:
                continue
            path, size = line.rsplit("\t", 1)
            path = path.strip("/")
            try:
                size = int(size)
            except ValueError:
                size = 0
            db.execute("INSERT OR REPLACE INTO remote_files(path,size) VALUES(?,?)", (path, size))

    seq = 0
    cursor = db.execute("SELECT path,size FROM remote_files ORDER BY path COLLATE NOCASE")
    for path, size in cursor:
        if Path(path).suffix.lower() not in exts:
            continue
        ann = annpath(path)
        found = db.execute("SELECT 1 FROM remote_files WHERE path=?", (ann,)).fetchone() is not None
        db.execute(
            "INSERT INTO catalog(seq,path,size,ann,annexists,assigned) VALUES(?,?,?,?,?,0)",
            (seq, path, int(size), ann, 1 if found else 0),
        )
        seq += 1
        if seq % 500 == 0:
            db.commit()
    db.execute("DELETE FROM remote_files")
    db.execute("INSERT INTO meta(key,value) VALUES('catalog_created',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now()),))
    db.commit()
    return seq


def freebytes(path):
    return shutil.disk_usage(path).free


def formatbytes(value):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(value)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def createbatch(cfg, db):
    if current(db) is not None:
        return current(db)
    bsize = integer(cfg, "BATCH_SIZE", 200)
    widx = integer(cfg, "WORKER_INDEX", 0)
    wcount = max(1, integer(cfg, "WORKER_COUNT", 1))
    rows = db.execute(
        "SELECT seq,path,ann,annexists,size FROM catalog WHERE assigned=0 AND (seq % ?) = ? ORDER BY seq LIMIT ?",
        (wcount, widx, bsize),
    ).fetchall()
    if not rows:
        return None
    total = sum(int(row[4]) for row in rows)
    need = int(total * number(cfg, "FREE_SPACE_FACTOR", 1.35))
    if freebytes(paths(cfg)["root"]) < need:
        raise RuntimeError(f"Not enough local free space for next batch: need about {formatbytes(need)}")
    cur = now()
    curid = db.execute(
        "INSERT INTO batches(state,expected,created,complete_at,uploaded_at,cleaned_at,attempts,error,next_at) VALUES('DOWNLOADING',?,?,0,0,0,0,NULL,0)",
        (len(rows), cur),
    ).lastrowid
    for seq, path, ann, exists, size in rows:
        db.execute(
            "INSERT INTO items(batch,seq,image,ann,annexists,state) VALUES(?,?,?,?,?,'PENDING')",
            (curid, seq, path, ann, exists),
        )
        db.execute("UPDATE catalog SET assigned=1 WHERE seq=?", (seq,))
    setcurrent(db, curid)
    db.execute("DELETE FROM meta WHERE key='app_closed_batch'")
    db.commit()
    batchdir = paths(cfg)["batches"] / f"batch_{curid:06d}"
    batchdir.mkdir(parents=True, exist_ok=True)
    (batchdir / "batch.id").write_text(str(curid), encoding="utf-8")
    symlink(paths(cfg)["current"], batchdir)
    return curid


def batchrows(db, bid):
    return db.execute(
        "SELECT seq,image,ann,annexists,basesize,basetime,basehash,localsize,localtime,localhash,backhash,state,error FROM items WHERE batch=? ORDER BY seq",
        (bid,),
    ).fetchall()


def filelist(cfg, db, bid, kind):
    out = paths(cfg)["tmp"] / f"list-{bid}-{kind}.txt"
    rows = batchrows(db, bid)
    with out.open("w", encoding="utf-8", newline="\n") as dst:
        for row in rows:
            if kind == "download":
                dst.write(row[1] + "\n")
                if int(row[3]):
                    dst.write(row[2] + "\n")
            elif kind == "annotation":
                local = paths(cfg)["batches"] / f"batch_{bid:06d}" / row[2]
                if local.exists():
                    dst.write(row[2] + "\n")
    return out


def remotejson(cfg, listfile, want_hash=False):
    args = [cfg.get("RCLONE_BIN", "rclone"), "lsjson", remote(cfg), "--files-from-raw", str(listfile), "--files-only", "--no-mimetype", "--no-traverse"]
    if want_hash:
        args += ["--hash"]
    code, text = cmdrun(args, timeout=300)
    if code != 0:
        return None, text
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return None, "Invalid rclone lsjson output"
    return data, ""


def remote_map(data):
    out = {}
    for item in data or []:
        path = item.get("Path") or item.get("Name")
        if path:
            hashes = item.get("Hashes") or {}
            out[path] = {
                "size": int(item.get("Size", 0)),
                "time": item.get("ModTime"),
                "hash": hashes.get("SHA-256") or hashes.get("SHA1") or hashes.get("MD5"),
            }
    return out


def remotetime(value):
    if not value:
        return None
    try:
        from datetime import datetime
        text = str(value).replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp())
    except Exception:
        return None


def baseline(cfg, db, bid):
    annfile = filelist(cfg, db, bid, "annotation")
    rows = batchrows(db, bid)
    existing = {row[2] for row in rows if int(row[3])}
    if not existing:
        try:
            annfile.unlink()
        except OSError:
            pass
        return
    want_hash = cfg.get("CONFLICT_MODE", "mtime_size") == "hash"
    data, err = remotejson(cfg, annfile, want_hash)
    try:
        annfile.unlink()
    except OSError:
        pass
    if data is None:
        raise RuntimeError(f"Unable to record remote annotation baseline: {err[:300]}")
    rem = remote_map(data)
    for row in rows:
        seq, image, ann, exists, *_ = row
        info = rem.get(ann)
        if info:
            local = paths(cfg)["batches"] / f"batch_{bid:06d}" / ann
            if local.exists():
                size = local.stat().st_size
                mtime = int(local.stat().st_mtime)
            else:
                size = info["size"]
                mtime = remotetime(info["time"])
            basehash = digest(local) if want_hash and local.exists() else None
            db.execute(
                "UPDATE items SET basesize=?,basetime=?,basehash=? WHERE batch=? AND seq=?",
                (info["size"], remotetime(info["time"]) or mtime, basehash, bid, seq),
            )
        else:
            db.execute("UPDATE items SET basesize=NULL,basetime=NULL,basehash=NULL,annexists=0 WHERE batch=? AND seq=?", (bid, seq))
    db.commit()


def download(cfg, db, bid):
    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    batchdir.mkdir(parents=True, exist_ok=True)
    listfile = filelist(cfg, db, bid, "download")
    args = [cfg.get("RCLONE_BIN", "rclone"), "copy", remote(cfg), str(batchdir), "--files-from-raw", str(listfile), "--no-traverse"]
    args += flags(cfg)
    code, text = cmdrun(args, timeout=integer(cfg, "TRANSFER_TIMEOUT_SECONDS", 1800))
    log(cfg, f"download-{bid:06d}", text)
    try:
        listfile.unlink()
    except OSError:
        pass
    if code != 0:
        attempts = db.execute("SELECT attempts FROM batches WHERE id=?", (bid,)).fetchone()[0] + 1
        wait = min(900, 30 * (2 ** min(attempts, 5)))
        db.execute("UPDATE batches SET attempts=?,error=?,next_at=? WHERE id=?", (attempts, text[-1000:], now() + wait, bid))
        db.commit()
        notify(cfg, "Annotation batch", f"Download failed for batch {bid}; retry scheduled")
        return False

    rows = batchrows(db, bid)
    missing = []
    for row in rows:
        image = batchdir / row[1]
        if not image.exists():
            missing.append(row[1])
    if missing:
        db.execute("UPDATE batches SET error=?,next_at=? WHERE id=?", (f"Missing {len(missing)} downloaded images", now() + 60, bid))
        db.commit()
        notify(cfg, "Annotation batch", f"Batch {bid} incomplete: {len(missing)} images missing")
        return False

    baseline(cfg, db, bid)
    backup(cfg, db, bid)
    db.execute("UPDATE batches SET state='ANNOTATING',attempts=0,error=NULL,next_at=0 WHERE id=?", (bid,))
    for row in rows:
        db.execute("UPDATE items SET state='PENDING',error=NULL WHERE batch=? AND seq=?", (bid, row[0]))
    db.commit()
    symlink(paths(cfg)["current"], batchdir)
    notify(cfg, "Annotation batch ready", f"Batch {bid} is ready: {len(rows)} images")
    return True


def backup(cfg, db, bid):
    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    target = paths(cfg)["backups"] / f"batch_{bid:06d}"
    target.mkdir(parents=True, exist_ok=True)
    for row in batchrows(db, bid):
        seq, image, ann, exists, basesize, basetime, basehash, lsize, ltime, lhash, backhash, state, error = row
        path = batchdir / ann
        if not path.exists():
            continue
        try:
            stat = path.stat()
            old = lhash
            if old and lsize == stat.st_size and ltime == int(stat.st_mtime_ns):
                continue
            dig = digest(path)
            dst = target / ann
            dst.parent.mkdir(parents=True, exist_ok=True)
            temp = dst.with_name(dst.name + ".tmp")
            shutil.copy2(path, temp)
            os.replace(temp, dst)
            db.execute(
                "UPDATE items SET localsize=?,localtime=?,localhash=?,backhash=?,state='ANNOTATED',error=NULL WHERE batch=? AND seq=?",
                (stat.st_size, int(stat.st_mtime_ns), dig, dig, bid, seq),
            )
        except OSError:
            continue
    db.commit()


def inspect(cfg, db, bid):
    row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
    if not row or row[0] not in {"ANNOTATING", "REVIEW_REQUIRED"}:
        return False, 0, 0

    backup(cfg, db, bid)
    stable = integer(cfg, "ANNOTATION_STABLE_SECONDS", 15)
    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    rows = batchrows(db, bid)
    total = len(rows)
    ready = 0
    missing = 0
    invalid = 0

    for row in rows:
        seq, image, ann, exists, basesize, basetime, basehash, lsize, ltime, lhash, backhash, state, error = row
        path = batchdir / ann
        if not path.exists():
            missing += 1
            db.execute(
                "UPDATE items SET state='UNANNOTATED',error=NULL WHERE batch=? AND seq=?",
                (bid, seq),
            )
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if time.time() - stat.st_mtime < stable:
            continue
        if not validjson(path):
            invalid += 1
            db.execute(
                "UPDATE items SET state='INVALID',error=? WHERE batch=? AND seq=?",
                ("Invalid JSON", bid, seq),
            )
            continue
        if lsize != stat.st_size or ltime != int(stat.st_mtime_ns):
            dig = digest(path)
            db.execute(
                "UPDATE items SET localsize=?,localtime=?,localhash=?,state='ANNOTATED',error=NULL WHERE batch=? AND seq=?",
                (stat.st_size, int(stat.st_mtime_ns), dig, bid, seq),
            )
            backup(cfg, db, bid)
        ready += 1

    # A batch is only finalized after XAnyLabeling has actually been closed.
    closed = str(meta(db, "app_closed_batch") or "") == str(bid)
    db.commit()

    if not closed:
        return False, ready, total

    if invalid:
        db.execute(
            "UPDATE batches SET state='REVIEW_REQUIRED',error=?,next_at=0 WHERE id=?",
            (f"{invalid} invalid annotation JSON file(s)", bid),
        )
        db.commit()
        notify(
            cfg,
            "Batch needs review",
            f"Batch {bid}: {invalid} invalid annotation file(s). Fix them before upload.",
        )
        return False, ready, total

    if missing == 0 and ready == total and total:
        stamp = now()
        db.execute(
            "UPDATE batches SET state='UPLOAD_PENDING',complete_at=?,error=NULL WHERE id=?",
            (stamp, bid),
        )
        db.commit()
        notify(
            cfg,
            "Batch complete",
            f"Batch {bid}: all {total} images have annotations. Upload is ready.",
        )
        return True, ready, total

    # Missing annotations are valid and may represent intentional background images.
    db.execute(
        "UPDATE batches SET state='AWAITING_APPROVAL',complete_at=?,error=? WHERE id=?",
        (now(), f"{missing} image(s) have no annotation", bid),
    )
    db.commit()
    notify(
        cfg,
        "Batch review required",
        f"Batch {bid}: {missing} image(s) have no annotation. User approval is required before upload.",
    )
    return False, ready, total


def conflict(cfg, db, bid):
    listfile = filelist(cfg, db, bid, "annotation")
    want_hash = cfg.get("CONFLICT_MODE", "mtime_size") == "hash"
    data, err = remotejson(cfg, listfile, want_hash)
    try:
        listfile.unlink()
    except OSError:
        pass
    if data is None:
        raise RuntimeError(f"Remote conflict check failed: {err[:300]}")
    rem = remote_map(data)
    rows = batchrows(db, bid)
    bad = []
    for row in rows:
        seq, image, ann, exists, basesize, basetime, basehash, lsize, ltime, lhash, backhash, state, error = row
        info = rem.get(ann)
        current_exists = info is not None
        if not int(exists):
            if current_exists:
                bad.append((seq, "Remote annotation appeared after batch download"))
            continue
        if not current_exists:
            bad.append((seq, "Remote annotation disappeared after batch download"))
            continue
        if want_hash and basehash and info.get("hash"):
            if info["hash"] != basehash:
                bad.append((seq, "Remote annotation hash changed"))
        else:
            sizeok = basesize is None or int(info.get("size", -1)) == int(basesize)
            timeok = True
            if basetime is not None and info.get("time"):
                rtime = remotetime(info.get("time"))
                if rtime is not None:
                    timeok = abs(rtime - int(basetime)) <= 1
            if not (sizeok and timeok):
                bad.append((seq, "Remote annotation changed since batch acquisition"))
    return bad


def upload(cfg, db, bid):
    row = db.execute("SELECT state,complete_at,next_at FROM batches WHERE id=?", (bid,)).fetchone()
    if not row:
        return False
    state, complete, nxt = row
    if state != "UPLOAD_PENDING":
        return False
    if now() < int(complete) + integer(cfg, "UPLOAD_GRACE_SECONDS", 20):
        return False
    if now() < int(nxt or 0):
        return False

    try:
        bad = conflict(cfg, db, bid)
    except Exception as exc:
        attempts = db.execute("SELECT attempts FROM batches WHERE id=?", (bid,)).fetchone()[0] + 1
        wait = min(900, 30 * (2 ** min(attempts, 5)))
        db.execute("UPDATE batches SET state='UPLOAD_PENDING',attempts=?,error=?,next_at=? WHERE id=?", (attempts, str(exc), now() + wait, bid))
        db.commit()
        return False
    if bad:
        for seq, text in bad:
            db.execute("UPDATE items SET state='CONFLICT',error=? WHERE batch=? AND seq=?", (text, bid, seq))
        db.execute("UPDATE batches SET state='CONFLICT',error=?,next_at=0 WHERE id=?", (f"{len(bad)} annotation conflict(s)", bid))
        db.commit()
        notify(cfg, "Annotation conflict", f"Batch {bid} has {len(bad)} conflict(s); no overwrite was performed")
        return False

    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    listfile = filelist(cfg, db, bid, "annotation")
    args = [cfg.get("RCLONE_BIN", "rclone"), "copy", str(batchdir), remote(cfg), "--files-from-raw", str(listfile), "--no-traverse", "--ignore-times"]
    args += flags(cfg)
    code, text = cmdrun(args, timeout=integer(cfg, "TRANSFER_TIMEOUT_SECONDS", 1800))
    log(cfg, f"upload-{bid:06d}", text)
    try:
        listfile.unlink()
    except OSError:
        pass
    if code != 0:
        attempts = db.execute("SELECT attempts FROM batches WHERE id=?", (bid,)).fetchone()[0] + 1
        wait = min(900, 30 * (2 ** min(attempts, 5)))
        db.execute("UPDATE batches SET state='UPLOAD_PENDING',attempts=?,error=?,next_at=? WHERE id=?", (attempts, text[-1000:], now() + wait, bid))
        db.commit()
        notify(cfg, "Annotation upload", f"Batch {bid} upload failed; local batch retained")
        return False

    # Verify only the batch annotation files, not the whole NAS tree.
    verifylist = filelist(cfg, db, bid, "annotation")
    data, err = remotejson(cfg, verifylist, cfg.get("VERIFY_MODE", "size") == "hash")
    try:
        verifylist.unlink()
    except OSError:
        pass
    if data is None:
        db.execute("UPDATE batches SET state='UPLOAD_PENDING',error=?,next_at=? WHERE id=?", (err[:500], now() + 60, bid))
        db.commit()
        return False
    rem = remote_map(data)
    failed = []
    for row in batchrows(db, bid):
        seq, image, ann, exists, basesize, basetime, basehash, lsize, ltime, lhash, backhash, state, error = row
        local = paths(cfg)["batches"] / f"batch_{bid:06d}" / ann
        # Intentionally unannotated/background images have no JSON to upload or verify.
        if not local.exists():
            continue
        info = rem.get(ann)
        if not info or int(info.get("size", -1)) != int(lsize or -1):
            failed.append(seq)
            continue
        if cfg.get("VERIFY_MODE", "size") == "hash" and lhash and info.get("hash") and info["hash"] != lhash:
            failed.append(seq)
    if failed:
        db.execute("UPDATE batches SET state='UPLOAD_PENDING',error=?,next_at=? WHERE id=?", (f"Verification failed for {len(failed)} file(s)", now() + 60, bid))
        db.commit()
        notify(cfg, "Annotation upload", f"Batch {bid} verification failed; local batch retained")
        return False

    stamp = now()
    db.execute("UPDATE batches SET state='SYNCED',uploaded_at=?,attempts=0,error=NULL,next_at=0 WHERE id=?", (stamp, bid))
    for row in batchrows(db, bid):
        seq = row[0]
        db.execute("UPDATE items SET state='SYNCED',error=NULL WHERE batch=? AND seq=?", (bid, seq))
    db.commit()
    notify(cfg, "Annotation upload", f"Batch {bid} synchronized successfully")
    return True


def cleanup(cfg, db, bid):
    if appactive(paths(cfg)["pid"]):
        return False
    if cfg.get("REQUIRE_APP_CLOSE", "1") == "1":
        closed = meta(db, "app_closed_batch")
        if str(closed or "") != str(bid):
            return False
    row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
    if not row or row[0] != "SYNCED":
        return False
    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    if batchdir.exists():
        shutil.rmtree(batchdir)
    db.execute("UPDATE catalog SET assigned=2 WHERE seq IN (SELECT seq FROM items WHERE batch=?)", (bid,))
    db.execute("UPDATE batches SET cleaned_at=?,state='CLEANED' WHERE id=?", (now(), bid))
    setcurrent(db, None)
    db.commit()
    try:
        if paths(cfg)["current"].is_symlink() or paths(cfg)["current"].exists():
            paths(cfg)["current"].unlink()
    except OSError:
        pass
    notify(cfg, "Annotation batch", f"Batch {bid} cleaned locally")
    return True


def prepare(cfg, db):
    if db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 0:
        raise RuntimeError("Dataset catalog is empty. Run 'catalog' first.")
    bid = current(db)
    if bid is None:
        bid = createbatch(cfg, db)
        if bid is None:
            meta(db, "done", 1)
            notify(cfg, "Annotation complete", "No more batches remain for this worker")
            return None
    state = db.execute("SELECT state,next_at FROM batches WHERE id=?", (bid,)).fetchone()
    if not state:
        setcurrent(db, None)
        return prepare(cfg, db)
    bstate, nxt = state
    if bstate == "DOWNLOADING" and now() >= int(nxt or 0):
        download(cfg, db, bid)
    return bid


def step(cfg, db):
    bid = current(db)
    if bid is None:
        if db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 0:
            return {"state": "NEEDS_CATALOG"}
        bid = createbatch(cfg, db)
        if bid is None:
            return {"state": "DONE"}
        download(cfg, db, bid)
        return status(cfg, db)

    row = db.execute("SELECT state,next_at FROM batches WHERE id=?", (bid,)).fetchone()
    if not row:
        setcurrent(db, None)
        return step(cfg, db)
    bstate, nxt = row
    if bstate == "DOWNLOADING":
        if now() >= int(nxt or 0):
            download(cfg, db, bid)
    elif bstate == "ANNOTATING":
        inspect(cfg, db, bid)
    elif bstate == "UPLOAD_PENDING":
        upload(cfg, db, bid)
    elif bstate == "SYNCED":
        cleanup(cfg, db, bid)
        if current(db) is None:
            new = createbatch(cfg, db)
            if new is not None:
                download(cfg, db, new)
            else:
                notify(cfg, "Annotation complete", "All assigned images are synchronized")
    elif bstate == "CONFLICT":
        pass
    elif bstate == "CLEANED":
        setcurrent(db, None)
    return status(cfg, db)


def status(cfg, db):
    total = db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
    done = db.execute("SELECT COUNT(*) FROM catalog WHERE assigned=2").fetchone()[0]
    bid = current(db)
    if bid is None:
        return {"catalog": total, "done": done, "batch": None, "state": "DONE" if total and done == total else "IDLE"}
    row = db.execute("SELECT state,expected,created,complete_at,uploaded_at,error,next_at FROM batches WHERE id=?", (bid,)).fetchone()
    counts = {}
    if row:
        counts["total"] = int(row[1])
        for state, count in db.execute("SELECT state,COUNT(*) FROM items WHERE batch=? GROUP BY state", (bid,)):
            counts[state] = int(count)
        return {
            "catalog": total,
            "done": done,
            "batch": bid,
            "state": row[0],
            "expected": row[1],
            "counts": counts,
            "created": row[2],
            "complete_at": row[3],
            "uploaded_at": row[4],
            "error": row[5],
            "next_at": row[6],
        }
    return {"catalog": total, "done": done, "batch": bid, "state": "UNKNOWN"}


def printstatus(cfg, db):
    data = status(cfg, db)
    print(json.dumps(data, indent=2))
    if data.get("batch"):
        print(f"\nLocal root: {cfg['ROOT']}")
        print(f"Current batch: {data['batch']} ({data['state']})")
        print(f"Dataset completed: {data['done']} / {data['catalog']}")
        print(f"Item states: {data.get('counts', {})}")


def closebatch(cfg, db):
    bid = current(db)
    if bid is None:
        raise RuntimeError("No current batch")
    db.execute("INSERT INTO meta(key,value) VALUES('app_closed_batch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(bid),))
    db.commit()
    return bid


def initstate(cfg, db):
    # Used only after a trusted manual import. Batch mode normally creates its own state.
    bid = current(db)
    if bid is not None:
        raise RuntimeError("Cannot reset state while a batch is active")
    db.execute("DELETE FROM catalog")
    db.execute("DELETE FROM remote_files")
    db.execute("DELETE FROM batches")
    db.execute("DELETE FROM items")
    db.execute("DELETE FROM meta WHERE key IN ('current_batch','done','catalog_created')")
    db.commit()


def review(cfg, db):
    bid = current(db)
    if bid is None:
        raise RuntimeError("No current batch")
    row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
    if not row:
        raise RuntimeError("Current batch state is missing")
    states = {state: int(count) for state, count in db.execute(
        "SELECT state,COUNT(*) FROM items WHERE batch=? GROUP BY state", (bid,)
    )}
    print(json.dumps({
        "batch": bid,
        "state": row[0],
        "total": sum(states.values()),
        "annotated": states.get("ANNOTATED", 0),
        "synced": states.get("SYNCED", 0),
        "unannotated": states.get("UNANNOTATED", 0),
        "invalid": states.get("INVALID", 0),
        "conflict": states.get("CONFLICT", 0),
    }, indent=2))
    missing = db.execute(
        "SELECT image FROM items WHERE batch=? AND state='UNANNOTATED' ORDER BY seq LIMIT 20",
        (bid,),
    ).fetchall()
    if missing:
        print("\\nImages without annotations (first 20):")
        for item in missing:
            print(f"  - {item[0]}")


def approve(cfg, db, choice):
    bid = current(db)
    if bid is None:
        raise RuntimeError("No current batch")
    row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
    if not row or row[0] != "AWAITING_APPROVAL":
        raise RuntimeError("Current batch is not awaiting approval")
    if choice == "yes":
        db.execute(
            "UPDATE batches SET state='UPLOAD_PENDING',error=NULL,complete_at=?,next_at=0 WHERE id=?",
            (now() - integer(cfg, "UPLOAD_GRACE_SECONDS", 20), bid),
        )
        db.commit()
        notify(cfg, "Batch approved", f"Batch {bid}: uploading available annotations; unannotated images will pass without JSON files.")
        return
    # No = wait. Keep the batch untouched so the user can resume later.
    print(f"Batch {bid} remains local. Upload has not started.")


def reopen(cfg, db):
    bid = current(db)
    if bid is None:
        raise RuntimeError("No current batch")
    row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
    if not row or row[0] not in {"AWAITING_APPROVAL", "REVIEW_REQUIRED"}:
        raise RuntimeError("Current batch does not need to be reopened")
    db.execute("UPDATE batches SET state='ANNOTATING',error=NULL,next_at=0 WHERE id=?", (bid,))
    db.execute("DELETE FROM meta WHERE key='app_closed_batch'")
    db.commit()
    return bid

def resolve(cfg, db, path, choice):
    bid = current(db)
    if bid is None:
        raise RuntimeError("No current batch")
    row = db.execute("SELECT seq,image,ann FROM items WHERE batch=? AND ann=?", (bid, path)).fetchone()
    if not row:
        raise RuntimeError("Annotation path is not part of the current batch")
    seq, image, ann = row
    batchdir = paths(cfg)["batches"] / f"batch_{bid:06d}"
    local = batchdir / ann
    if choice == "remote":
        tmp = batchdir / (ann + ".remote.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        src = remote(cfg, ann)
        code, text = cmdrun([cfg.get("RCLONE_BIN", "rclone"), "copyto", src, str(tmp)] + flags(cfg), timeout=300)
        if code != 0:
            raise RuntimeError(text[-500:])
        os.replace(tmp, local)
    elif choice != "local":
        raise RuntimeError("choice must be local or remote")
    listfile = paths(cfg)["tmp"] / f"resolve-{bid}.txt"
    listfile.write_text(ann + "\n", encoding="utf-8")
    data, err = remotejson(cfg, listfile, cfg.get("CONFLICT_MODE", "mtime_size") == "hash")
    try:
        listfile.unlink()
    except OSError:
        pass
    if data is None:
        raise RuntimeError(err)
    rem = remote_map(data).get(ann)
    stat = local.stat()
    localhash = digest(local)
    if rem:
        db.execute(
            "UPDATE items SET annexists=1,basesize=?,basetime=?,basehash=?,localsize=?,localtime=?,localhash=?,backhash=?,state='ANNOTATED',error=NULL WHERE batch=? AND seq=?",
            (rem["size"], remotetime(rem["time"]) or int(stat.st_mtime), rem.get("hash"), stat.st_size, int(stat.st_mtime_ns), localhash, localhash, bid, seq),
        )
    else:
        db.execute(
            "UPDATE items SET annexists=0,basesize=NULL,basetime=NULL,basehash=NULL,localsize=?,localtime=?,localhash=?,backhash=?,state='ANNOTATED',error=NULL WHERE batch=? AND seq=?",
            (stat.st_size, int(stat.st_mtime_ns), localhash, localhash, bid, seq),
        )
    db.execute("UPDATE batches SET state='UPLOAD_PENDING',error=NULL,complete_at=? WHERE id=?", (now() - integer(cfg, "UPLOAD_GRACE_SECONDS", 20), bid))
    db.commit()


def cleanbackups(cfg, db):
    keep = integer(cfg, "BACKUP_RETENTION_DAYS", 2) * 86400
    cut = now() - keep
    removed = 0
    for folder in paths(cfg)["backups"].glob("batch_*"):
        if not folder.is_dir():
            continue
        try:
            bid = int(folder.name.split("_")[-1])
        except ValueError:
            continue
        row = db.execute("SELECT state,cleaned_at FROM batches WHERE id=?", (bid,)).fetchone()
        if not row or row[0] != "CLEANED":
            continue
        if int(row[1] or 0) > cut:
            continue
        shutil.rmtree(folder)
        removed += 1
    return removed


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("catalog")
    sub.add_parser("prepare")
    sub.add_parser("step")
    sub.add_parser("sync")
    sub.add_parser("status")
    sub.add_parser("review")
    sub.add_parser("cleanup")
    sub.add_parser("close")
    app = sub.add_parser("approve")
    app.add_argument("choice", choices=["yes", "no"])
    sub.add_parser("reopen")
    res = sub.add_parser("resolve")
    res.add_argument("path")
    res.add_argument("choice", choices=["local", "remote"])
    args = parser.parse_args()
    cfg = envcfg()

    # Read-only status/review commands must not resurrect a deleted workspace.
    # This also prevents a still-open GUI that polls status from recreating ROOT.
    configured_root = Path(cfg["ROOT"]).expanduser()
    if args.action in {"status", "review"} and not configured_root.exists():
        if args.action == "status":
            print(json.dumps({"state": "WORKSPACE_ABSENT", "catalog": 0, "done": 0, "batch": None}))
            print(f"Local root: {configured_root}")
            print("Workspace does not exist. It will be created only by an explicit operational command.")
        else:
            print(f"Workspace does not exist: {configured_root}")
        return 0

    out = ensurepaths(cfg)
    handle = lock(out["lock"])
    if handle is None and args.action in {"catalog", "prepare", "step", "sync", "cleanup", "resolve", "approve", "reopen"}:
        print("Another manager process is active; exiting.")
        return 0
    db = dbopen(out["db"])
    try:
        guardconfig(cfg, db)
        if args.action == "catalog":
            print(f"Cataloging {cfg['REMOTE']}:{cfg['DATASET']} ...")
            count = catalog(cfg, db)
            print(f"Catalog complete: {count} images")
        elif args.action == "prepare":
            if db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 0:
                count = catalog(cfg, db)
                print(f"Catalog complete: {count} images")
            data = prepare(cfg, db)
            printstatus(cfg, db)
            if data is None:
                return 2
        elif args.action in {"step", "sync"}:
            if args.action == "step" and not due(db, cfg):
                printstatus(cfg, db)
                return 0
            markrun(db)
            printstatus(cfg, db)
            if db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 0:
                count = catalog(cfg, db)
                print(f"Catalog complete: {count} images")
            data = step(cfg, db)
            printstatus(cfg, db)
            if data.get("state") == "NEEDS_CATALOG":
                return 2
        elif args.action == "status":
            printstatus(cfg, db)
        elif args.action == "review":
            review(cfg, db)
        elif args.action == "cleanup":
            count = cleanbackups(cfg, db)
            print(f"Removed {count} expired backup batch(es).")
        elif args.action == "close":
            bid = closebatch(cfg, db)
            print(f"Batch {bid} marked closed; checking annotation completion.")
            step(cfg, db)
            printstatus(cfg, db)
        elif args.action == "approve":
            approve(cfg, db, args.choice)
            printstatus(cfg, db)
        elif args.action == "reopen":
            bid = reopen(cfg, db)
            print(f"Batch {bid} reopened for annotation.")
            printstatus(cfg, db)
        elif args.action == "resolve":
            resolve(cfg, db, args.path, args.choice)
            printstatus(cfg, db)
    finally:
        db.close()
        try:
            handle.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
