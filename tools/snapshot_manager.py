from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
PORTAL_DB = BASE_DIR / "portal.db"
LEGACY_DB = BASE_DIR / "relay.db"
PORTAL_ENV = BASE_DIR / ".env"
RUN_DIR = BASE_DIR / "run"
SECRET_FILE = RUN_DIR / "portal-session-secret.txt"
SERVICE_FILE = RUN_DIR / "services.json"
UPSTREAM_DB = BASE_DIR / "upstream" / "data" / "data.sqlite3"
SNAPSHOT_DIR = Path(os.getenv("RELAY_SNAPSHOT_DIR", str(BASE_DIR / "snapshots"))).resolve()
DEFAULT_KEEP_LATEST = int(os.getenv("RELAY_SNAPSHOT_KEEP_LATEST", "20"))


class SnapshotError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SnapshotTarget:
    key: str
    source: Path
    archive_path: str
    kind: str = "file"
    required: bool = True


def isoformat(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    return current.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_targets() -> list[SnapshotTarget]:
    return [
        SnapshotTarget("portal_db", PORTAL_DB, "portal/portal.db", kind="sqlite"),
        SnapshotTarget("upstream_db", UPSTREAM_DB, "upstream/data.sqlite3", kind="sqlite"),
        SnapshotTarget("portal_secret", SECRET_FILE, "portal/portal-session-secret.txt", required=False),
        SnapshotTarget("portal_env", PORTAL_ENV, "portal/.env", required=False),
        SnapshotTarget("service_state", SERVICE_FILE, "metadata/services.json", required=False),
        SnapshotTarget("legacy_relay_db", LEGACY_DB, "legacy/relay.db", kind="sqlite", required=False),
    ]


def ensure_snapshot_dir() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def build_snapshot_id(label: str | None = None) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = slugify(label or "")
    return f"{timestamp}-{suffix}" if suffix else timestamp


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        raise SnapshotError(f"SQLite source not found: {source}")

    src_conn = sqlite3.connect(source)
    dst_conn = sqlite3.connect(destination)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def capture_target(target: SnapshotTarget, staging_dir: Path) -> dict[str, Any] | None:
    if not target.source.exists():
        if target.required:
            raise SnapshotError(f"Snapshot source not found: {target.source}")
        return None

    staged_file = staging_dir / target.archive_path
    staged_file.parent.mkdir(parents=True, exist_ok=True)

    if target.kind == "sqlite":
        backup_sqlite(target.source, staged_file)
    else:
        shutil.copy2(target.source, staged_file)

    return {
        "key": target.key,
        "kind": target.kind,
        "required": target.required,
        "source": str(target.source),
        "archivePath": target.archive_path,
        "sizeBytes": staged_file.stat().st_size,
        "sha256": file_sha256(staged_file),
    }


def write_archive(staging_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file_path in sorted(staging_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(staging_dir).as_posix())


def manifest_from_archive(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        with archive.open("manifest.json", "r") as handle:
            manifest = json.load(handle)
    manifest["archivePath"] = str(archive_path)
    manifest["archiveSizeBytes"] = archive_path.stat().st_size
    return manifest


def list_snapshots(*, limit: int | None = None) -> list[dict[str, Any]]:
    root = ensure_snapshot_dir()
    snapshots: list[dict[str, Any]] = []
    archives = sorted(root.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)

    for archive_path in archives:
        try:
            snapshots.append(manifest_from_archive(archive_path))
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            continue
        if limit and len(snapshots) >= limit:
            break
    return snapshots


def prune_snapshots(*, keep_latest: int | None = None) -> list[str]:
    keep = keep_latest if keep_latest is not None else DEFAULT_KEEP_LATEST
    if keep <= 0:
        return []

    archives = sorted(ensure_snapshot_dir().glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    deleted: list[str] = []
    for archive_path in archives[keep:]:
        archive_path.unlink(missing_ok=True)
        deleted.append(str(archive_path))
    return deleted


def create_snapshot(
    *,
    label: str | None = None,
    keep_latest: int | None = None,
    created_by: str = "cli",
) -> dict[str, Any]:
    snapshot_id = build_snapshot_id(label)
    archive_path = ensure_snapshot_dir() / f"{snapshot_id}.zip"

    with tempfile.TemporaryDirectory(prefix=f"{snapshot_id}-", dir=str(ensure_snapshot_dir())) as temp_dir_name:
        staging_dir = Path(temp_dir_name)
        items = []
        for target in snapshot_targets():
            item = capture_target(target, staging_dir)
            if item:
                items.append(item)

        manifest = {
            "schemaVersion": 1,
            "id": snapshot_id,
            "label": label or "",
            "createdAt": isoformat(),
            "createdBy": created_by,
            "host": socket.gethostname(),
            "items": items,
            "restoreCommand": f"python tools/snapshot_manager.py restore --snapshot {snapshot_id}",
        }
        (staging_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        write_archive(staging_dir, archive_path)

    deleted = prune_snapshots(keep_latest=keep_latest)
    created = manifest_from_archive(archive_path)
    created["prunedArchives"] = deleted
    return created


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def active_service_pids() -> list[int]:
    if not SERVICE_FILE.exists():
        return []

    try:
        payload = json.loads(SERVICE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    active: list[int] = []
    for key in ("portalPid", "adminPid"):
        raw = payload.get(key)
        if isinstance(raw, int) and raw > 0 and process_alive(raw):
            active.append(raw)
    return active


def resolve_snapshot(snapshot: str) -> Path:
    candidate = Path(snapshot)
    if candidate.exists():
        return candidate.resolve()

    root = ensure_snapshot_dir()
    direct = root / f"{snapshot}.zip"
    if direct.exists():
        return direct.resolve()

    matches = sorted(root.glob(f"{snapshot}*.zip"))
    if not matches:
        raise SnapshotError(f"Snapshot not found: {snapshot}")
    if len(matches) > 1:
        raise SnapshotError(f"Snapshot is ambiguous: {snapshot}")
    return matches[0].resolve()


def verify_staged_items(extract_root: Path, manifest: dict[str, Any]) -> None:
    for item in manifest.get("items", []):
        staged_file = extract_root / str(item["archivePath"])
        if not staged_file.exists():
            raise SnapshotError(f"Snapshot item missing: {item['archivePath']}")
        checksum = file_sha256(staged_file)
        if checksum != item.get("sha256"):
            raise SnapshotError(f"Checksum mismatch for: {item['archivePath']}")


def cleanup_sqlite_sidecars(target: Path) -> None:
    target.with_name(f"{target.name}-wal").unlink(missing_ok=True)
    target.with_name(f"{target.name}-shm").unlink(missing_ok=True)


def restore_snapshot(
    snapshot: str,
    *,
    force_live: bool = False,
    dry_run: bool = False,
    create_safety_snapshot: bool = True,
    restored_by: str = "cli",
) -> dict[str, Any]:
    archive_path = resolve_snapshot(snapshot)
    manifest = manifest_from_archive(archive_path)
    active_pids = active_service_pids()
    if active_pids and not force_live:
        raise SnapshotError(
            "Detected running services. Stop the stack before restore, or rerun with --force-live if you accept live restore risk."
        )

    safety_snapshot: dict[str, Any] | None = None
    if create_safety_snapshot and not dry_run:
        safety_snapshot = create_snapshot(
            label=f"pre-restore-{manifest['id']}",
            keep_latest=0,
            created_by=f"{restored_by}:safety",
        )

    with tempfile.TemporaryDirectory(prefix=f"restore-{manifest['id']}-", dir=str(ensure_snapshot_dir())) as temp_dir_name:
        extract_root = Path(temp_dir_name)
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(extract_root)

        verify_staged_items(extract_root, manifest)

        if not dry_run:
            target_lookup = {target.key: target for target in snapshot_targets()}
            for item in manifest.get("items", []):
                target = target_lookup.get(str(item["key"]))
                if not target:
                    continue
                staged_file = extract_root / str(item["archivePath"])
                target.source.parent.mkdir(parents=True, exist_ok=True)
                if target.kind == "sqlite":
                    cleanup_sqlite_sidecars(target.source)
                shutil.copy2(staged_file, target.source)

    return {
        "ok": True,
        "snapshotId": manifest["id"],
        "archivePath": str(archive_path),
        "dryRun": dry_run,
        "restoredAt": isoformat(),
        "restoredBy": restored_by,
        "safetySnapshot": safety_snapshot,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Relay snapshot archives.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a new snapshot archive.")
    create_parser.add_argument("--label", default="")
    create_parser.add_argument("--keep-latest", type=int, default=DEFAULT_KEEP_LATEST)
    create_parser.add_argument("--created-by", default="cli")
    create_parser.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list", help="List snapshot archives.")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--json", action="store_true")

    restore_parser = subparsers.add_parser("restore", help="Restore from a snapshot archive.")
    restore_parser.add_argument("--snapshot", required=True)
    restore_parser.add_argument("--force-live", action="store_true")
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--skip-safety-snapshot", action="store_true")
    restore_parser.add_argument("--restored-by", default="cli")
    restore_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        if args.command == "create":
            result = create_snapshot(label=args.label or None, keep_latest=args.keep_latest, created_by=args.created_by)
        elif args.command == "list":
            result = {"snapshots": list_snapshots(limit=args.limit)}
        else:
            result = restore_snapshot(
                args.snapshot,
                force_live=args.force_live,
                dry_run=args.dry_run,
                create_safety_snapshot=not args.skip_safety_snapshot,
                restored_by=args.restored_by,
            )
    except SnapshotError as exc:
        raise SystemExit(str(exc)) from exc

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "list":
        for snapshot in result["snapshots"]:
            print(f"{snapshot['id']}  {snapshot['createdAt']}  {snapshot['archivePath']}")
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
