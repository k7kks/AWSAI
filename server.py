from __future__ import annotations

from dataclasses import dataclass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import hmac
import os
import asyncio
import ipaddress
import sqlite3
import json
import secrets
import argparse
import shutil
import socket
import threading
from hashlib import pbkdf2_hmac
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, make_response, request, send_file, send_from_directory, stream_with_context
from waitress import serve
from tools.snapshot_manager import DEFAULT_KEEP_LATEST, create_snapshot, list_snapshots, resolve_snapshot
from registration_service import get_registration_service


BASE_DIR = Path(__file__).resolve().parent
ASSET_DIR = BASE_DIR / "assets"
DB_PATH = BASE_DIR / "portal.db"
RUN_DIR = BASE_DIR / "run"
SECRET_FILE = RUN_DIR / "portal-session-secret.txt"

USER_COOKIE = "relay_user_session"
ADMIN_COOKIE = "relay_admin_session"

HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "content-encoding",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

PLAN_PROFILES: dict[str, dict[str, Any]] = {
    "starter": {
        "label": "Starter",
        "daily_quota": 200_000,
        "monthly_quota": 3_000_000,
        "request_quota": 1_000,
        "rate_limit_rpm": 30,
        "description": "适合个人试用、低频工作流和内部验证。",
    },
    "growth": {
        "label": "Growth",
        "daily_quota": 600_000,
        "monthly_quota": 10_000_000,
        "request_quota": 5_000,
        "rate_limit_rpm": 80,
        "description": "适合稳定团队使用和轻量商业化运营。",
    },
    "partner": {
        "label": "Partner",
        "daily_quota": 1_500_000,
        "monthly_quota": 30_000_000,
        "request_quota": 15_000,
        "rate_limit_rpm": 180,
        "description": "适合多租户中转、面向客户的正式套餐。",
    },
}

ENTRY_PROVIDERS: dict[str, dict[str, Any]] = {
    "kiro": {
        "label": "Kiro Relay",
        "kind": "native",
        "enabled": 1,
        "sort_order": 10,
        "description": "当前内置门户与管理后台。",
        "embed_mode": "native",
    },
    "sub2api": {
        "label": "Sub2API",
        "kind": "external",
        "enabled": 0,
        "sort_order": 20,
        "description": "外部 Sub2API 门户入口。",
        "embed_mode": "link",
    },
}

ALLOWED_ENTRY_EMBED_MODES = {"native", "link", "new_tab", "iframe"}
SUB2API_SOURCE_DIR = BASE_DIR / "sub2api-main" / "sub2api-main"
SUB2API_MANAGED_FIELD_ENV_MAP = {
    "label": "RELAY_SUB2API_LABEL",
    "description": "RELAY_SUB2API_DESCRIPTION",
    "enabled": "RELAY_SUB2API_ENABLED",
    "public_url": "RELAY_SUB2API_PUBLIC_URL",
    "admin_url": "RELAY_SUB2API_ADMIN_URL",
    "api_base_url": "RELAY_SUB2API_API_BASE_URL",
    "health_url": "RELAY_SUB2API_HEALTH_URL",
    "admin_api_key_encrypted": "RELAY_SUB2API_ADMIN_API_KEY",
    "default_allowed_groups": "RELAY_SUB2API_DEFAULT_ALLOWED_GROUPS",
    "default_concurrency": "RELAY_SUB2API_DEFAULT_CONCURRENCY",
    "initial_balance": "RELAY_SUB2API_INITIAL_BALANCE",
    "embed_mode": "RELAY_SUB2API_EMBED_MODE",
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_runtime_secret() -> str:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


@dataclass(slots=True)
class Settings:
    upstream_url: str
    upstream_admin_password: str
    public_portal_base_url: str
    public_api_base_url: str
    public_admin_base_url: str
    session_secret: str
    cookie_secure: bool
    user_session_hours: int
    admin_session_hours: int
    connect_timeout: int
    read_timeout: int
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    bootstrap_admin_name: str
    encryption_key: bytes


def load_settings() -> Settings:
    load_env_file(BASE_DIR / ".env")
    session_secret = os.getenv("RELAY_SESSION_SECRET", "").strip() or ensure_runtime_secret()
    
    # Generate or load encryption key for sensitive data
    key_file = RUN_DIR / "encryption.key"
    if key_file.exists():
        encryption_key = key_file.read_bytes()
    else:
        # Generate a new key
        salt = secrets.token_bytes(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(session_secret.encode()))
        key_file.write_bytes(key)
        encryption_key = key

    return Settings(
        upstream_url=os.getenv("RELAY_UPSTREAM_URL", "http://127.0.0.1:62311").rstrip("/"),
        upstream_admin_password=os.getenv("RELAY_UPSTREAM_ADMIN_PASSWORD", "").strip(),
        public_portal_base_url=os.getenv("RELAY_PUBLIC_PORTAL_BASE_URL", "").rstrip("/"),
        public_api_base_url=os.getenv("RELAY_PUBLIC_API_BASE_URL", "").rstrip("/"),
        public_admin_base_url=os.getenv("RELAY_PUBLIC_ADMIN_BASE_URL", "").rstrip("/"),
        session_secret=session_secret,
        cookie_secure=env_bool("RELAY_COOKIE_SECURE", False),
        user_session_hours=int(os.getenv("RELAY_USER_SESSION_HOURS", "168")),
        admin_session_hours=int(os.getenv("RELAY_ADMIN_SESSION_HOURS", "24")),
        connect_timeout=int(os.getenv("RELAY_CONNECT_TIMEOUT", "10")),
        read_timeout=int(os.getenv("RELAY_READ_TIMEOUT", "300")),
        bootstrap_admin_email=os.getenv("RELAY_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower(),
        bootstrap_admin_password=os.getenv("RELAY_BOOTSTRAP_ADMIN_PASSWORD", ""),
        bootstrap_admin_name=os.getenv("RELAY_BOOTSTRAP_ADMIN_NAME", "Relay Admin").strip() or "Relay Admin",
        encryption_key=encryption_key,
    )


SETTINGS = load_settings()


class PortalError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UpstreamUnavailableError(PortalError):
    def __init__(self, message: str = "上游中转服务不可用。") -> None:
        super().__init__(message, 502)


def now_utc() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None = None) -> str:
    current = value or now_utc()
    return current.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def password_hash(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$", 1)
    candidate = password_hash(password, salt_hex).split("$", 1)[1]
    return hmac.compare_digest(candidate, digest_hex)


def encrypt_data(data: str) -> str:
    """Encrypt sensitive data"""
    f = Fernet(SETTINGS.encryption_key)
    return f.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    """Decrypt sensitive data"""
    f = Fernet(SETTINGS.encryption_key)
    return f.decrypt(encrypted_data.encode()).decode()


def format_exception_message(error: BaseException) -> str:
    details = str(error).strip()
    if details:
        return f"{type(error).__name__}: {details}"
    return type(error).__name__


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    existing_columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing_columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def open_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_database() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with open_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL UNIQUE,
                workspace TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                plan_key TEXT NOT NULL,
                usecase TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                upstream_user_id TEXT NOT NULL UNIQUE,
                upstream_api_key TEXT NOT NULL,
                daily_quota INTEGER NOT NULL,
                monthly_quota INTEGER NOT NULL,
                request_quota INTEGER NOT NULL,
                rate_limit_rpm INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_entry_providers (
                entry_key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                description TEXT NOT NULL DEFAULT '',
                public_url TEXT NOT NULL DEFAULT '',
                admin_url TEXT NOT NULL DEFAULT '',
                api_base_url TEXT NOT NULL DEFAULT '',
                health_url TEXT NOT NULL DEFAULT '',
                admin_api_key_encrypted TEXT NOT NULL DEFAULT '',
                default_allowed_groups TEXT NOT NULL DEFAULT '',
                default_concurrency INTEGER NOT NULL DEFAULT 0,
                initial_balance REAL NOT NULL DEFAULT 0,
                embed_mode TEXT NOT NULL DEFAULT 'link',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_sessions (
                token TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                subject_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_portal_sessions_role_subject ON portal_sessions(role, subject_id)")
        # Registration manager tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_encrypted TEXT,
                microsoft_refresh_token TEXT NOT NULL,
                microsoft_client_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                aws_builder_id TEXT,
                kiro_config_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_registration_attempt TEXT,
                registration_attempts INTEGER DEFAULT 0,
                error_message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                total_accounts INTEGER DEFAULT 0,
                completed_accounts INTEGER DEFAULT 0,
                failed_accounts INTEGER DEFAULT 0,
                concurrency INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                job_id INTEGER,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                step TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES registration_accounts (id),
                FOREIGN KEY (job_id) REFERENCES registration_jobs (id)
            )
            """
        )
        ensure_column(conn, "registration_accounts", "password_encrypted", "TEXT")
        ensure_column(conn, "portal_users", "provider_key", "TEXT NOT NULL DEFAULT 'kiro'")
        ensure_column(conn, "portal_entry_providers", "admin_api_key_encrypted", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "portal_entry_providers", "default_allowed_groups", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "portal_entry_providers", "default_concurrency", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "portal_entry_providers", "initial_balance", "REAL NOT NULL DEFAULT 0")
        seed_entry_providers(conn)
        apply_env_managed_provider_overrides(conn)
        conn.commit()


def seed_entry_providers(conn: sqlite3.Connection) -> None:
    now = isoformat()
    for entry_key, defaults in ENTRY_PROVIDERS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO portal_entry_providers (
                entry_key, label, kind, enabled, sort_order, description,
                public_url, admin_url, api_base_url, health_url,
                admin_api_key_encrypted, default_allowed_groups, default_concurrency, initial_balance,
                embed_mode,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '', '', '', '', '', '', 0, 0, ?, ?, ?)
            """,
            (
                entry_key,
                defaults["label"],
                defaults["kind"],
                int(defaults["enabled"]),
                int(defaults["sort_order"]),
                defaults["description"],
                defaults["embed_mode"],
                now,
                now,
            ),
        )


def request_origin() -> str:
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{proto}://{host}".rstrip("/")


def portal_base_url() -> str:
    return SETTINGS.public_portal_base_url or request_origin()


def api_base_url() -> str:
    return SETTINGS.public_api_base_url or f"{request_origin()}/v1"


def admin_base_url() -> str:
    return SETTINGS.public_admin_base_url or request_origin()


def normalize_optional_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PortalError("URL 必须是有效的 http(s) 地址。")
    return text.rstrip("/")


def parse_optional_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value).split(",")

    items: list[int] = []
    for raw in raw_items:
        text = str(raw).strip()
        if not text:
            continue
        try:
            number = int(text)
        except ValueError as exc:
            raise PortalError("默认分组必须是整数 ID。") from exc
        if number <= 0:
            raise PortalError("默认分组必须是正整数 ID。")
        items.append(number)
    return items


def env_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip()


def env_present(name: str) -> bool:
    return os.getenv(name) is not None


def entry_provider_env_overrides(entry_key: str) -> dict[str, Any]:
    if entry_key != "sub2api":
        return {"managed_fields": [], "values": {}}

    managed_fields: list[str] = []
    values: dict[str, Any] = {}

    base_url = None
    if env_present("RELAY_SUB2API_BASE_URL"):
        base_url = normalize_optional_url(env_text("RELAY_SUB2API_BASE_URL"))

    label = env_text("RELAY_SUB2API_LABEL")
    if label:
        managed_fields.append("label")
        values["label"] = label

    description = env_text("RELAY_SUB2API_DESCRIPTION")
    if description is not None:
        managed_fields.append("description")
        values["description"] = description

    if env_present("RELAY_SUB2API_ENABLED"):
        managed_fields.append("enabled")
        values["enabled"] = env_bool("RELAY_SUB2API_ENABLED", False)

    if env_present("RELAY_SUB2API_EMBED_MODE"):
        embed_mode = (env_text("RELAY_SUB2API_EMBED_MODE") or "link").lower()
        if embed_mode not in ALLOWED_ENTRY_EMBED_MODES:
            raise PortalError("RELAY_SUB2API_EMBED_MODE 配置无效。", 500)
        managed_fields.append("embed_mode")
        values["embed_mode"] = embed_mode

    url_fields = {
        "public_url": "RELAY_SUB2API_PUBLIC_URL",
        "admin_url": "RELAY_SUB2API_ADMIN_URL",
        "api_base_url": "RELAY_SUB2API_API_BASE_URL",
        "health_url": "RELAY_SUB2API_HEALTH_URL",
    }
    derived_from_base = {
        "public_url": base_url,
        "admin_url": f"{base_url}/admin".rstrip("/") if base_url else None,
        "api_base_url": f"{base_url}/v1".rstrip("/") if base_url else None,
        "health_url": f"{base_url}/health".rstrip("/") if base_url else None,
    }
    for field_name, env_name in url_fields.items():
        if env_present(env_name):
            managed_fields.append(field_name)
            values[field_name] = normalize_optional_url(env_text(env_name))
            continue
        if base_url:
            managed_fields.append(field_name)
            values[field_name] = derived_from_base[field_name]

    if env_present("RELAY_SUB2API_ADMIN_API_KEY"):
        admin_api_key = env_text("RELAY_SUB2API_ADMIN_API_KEY") or ""
        managed_fields.append("admin_api_key_encrypted")
        values["admin_api_key_encrypted"] = encrypt_data(admin_api_key) if admin_api_key else ""

    if env_present("RELAY_SUB2API_DEFAULT_ALLOWED_GROUPS"):
        managed_fields.append("default_allowed_groups")
        values["default_allowed_groups"] = json.dumps(parse_optional_int_list(env_text("RELAY_SUB2API_DEFAULT_ALLOWED_GROUPS")))

    if env_present("RELAY_SUB2API_DEFAULT_CONCURRENCY"):
        try:
            default_concurrency = int(env_text("RELAY_SUB2API_DEFAULT_CONCURRENCY") or "0")
        except ValueError as exc:
            raise PortalError("RELAY_SUB2API_DEFAULT_CONCURRENCY 必须是整数。", 500) from exc
        if default_concurrency < 0:
            raise PortalError("RELAY_SUB2API_DEFAULT_CONCURRENCY 不能小于 0。", 500)
        managed_fields.append("default_concurrency")
        values["default_concurrency"] = default_concurrency

    if env_present("RELAY_SUB2API_INITIAL_BALANCE"):
        try:
            initial_balance = float(env_text("RELAY_SUB2API_INITIAL_BALANCE") or "0")
        except ValueError as exc:
            raise PortalError("RELAY_SUB2API_INITIAL_BALANCE 必须是数字。", 500) from exc
        if initial_balance < 0:
            raise PortalError("RELAY_SUB2API_INITIAL_BALANCE 不能小于 0。", 500)
        managed_fields.append("initial_balance")
        values["initial_balance"] = initial_balance

    return {"managed_fields": managed_fields, "values": values}


def entry_provider_managed_fields(entry_key: str) -> list[str]:
    return list(entry_provider_env_overrides(entry_key).get("managed_fields") or [])


def apply_env_managed_provider_overrides(conn: sqlite3.Connection) -> None:
    now = isoformat()
    for entry_key in ENTRY_PROVIDERS:
        override = entry_provider_env_overrides(entry_key)
        values = override.get("values") or {}
        if not values:
            continue
        row = conn.execute(
            "SELECT * FROM portal_entry_providers WHERE entry_key = ?",
            (entry_key,),
        ).fetchone()
        if not row:
            continue
        conn.execute(
            """
            UPDATE portal_entry_providers
            SET label = ?, enabled = ?, description = ?, public_url = ?, admin_url = ?,
                api_base_url = ?, health_url = ?, admin_api_key_encrypted = ?, default_allowed_groups = ?,
                default_concurrency = ?, initial_balance = ?, embed_mode = ?, updated_at = ?
            WHERE entry_key = ?
            """,
            (
                values.get("label", row["label"]),
                1 if bool(values.get("enabled", bool(row["enabled"]))) else 0,
                values.get("description", row["description"] or ""),
                values.get("public_url", row["public_url"] or ""),
                values.get("admin_url", row["admin_url"] or ""),
                values.get("api_base_url", row["api_base_url"] or ""),
                values.get("health_url", row["health_url"] or ""),
                values.get("admin_api_key_encrypted", row["admin_api_key_encrypted"] or ""),
                values.get("default_allowed_groups", row["default_allowed_groups"] or "[]"),
                int(values.get("default_concurrency", row["default_concurrency"] or 0)),
                float(values.get("initial_balance", row["initial_balance"] or 0)),
                values.get("embed_mode", row["embed_mode"] or "link"),
                now,
                entry_key,
            ),
        )


def list_entry_provider_rows() -> list[sqlite3.Row]:
    with open_db() as conn:
        return conn.execute(
            "SELECT * FROM portal_entry_providers ORDER BY sort_order ASC, entry_key ASC"
        ).fetchall()


def find_entry_provider_row(entry_key: str) -> sqlite3.Row:
    with open_db() as conn:
        row = conn.execute(
            "SELECT * FROM portal_entry_providers WHERE entry_key = ?",
            (entry_key,),
        ).fetchone()
    if not row:
        raise PortalError("入口不存在。", 404)
    return row


def serialize_entry_provider_by_key(entry_key: str, *, include_health: bool = False) -> dict[str, Any]:
    try:
        row = find_entry_provider_row(entry_key)
    except PortalError:
        row = find_entry_provider_row("kiro")
    return serialize_entry_provider(row, include_health=include_health)


def derive_entry_health_url(*, public_url: str, admin_url: str, api_base_url: str) -> str:
    if api_base_url:
        api_url = api_base_url.rstrip("/")
        if api_url.endswith("/v1"):
            return f"{api_url[:-3]}/health".rstrip("/")
        return f"{api_url}/health"
    if public_url:
        return f"{public_url.rstrip('/')}/health"
    if admin_url:
        return f"{admin_url.rstrip('/')}/health"
    return ""


def serialize_entry_provider(row: sqlite3.Row, *, include_health: bool = False) -> dict[str, Any]:
    entry_key = row["entry_key"]
    is_native = row["kind"] == "native"
    managed_fields = entry_provider_managed_fields(entry_key)
    public_url = portal_base_url() if is_native else str(row["public_url"] or "").rstrip("/")
    admin_url = admin_base_url() if is_native else str(row["admin_url"] or "").rstrip("/")
    api_url = api_base_url() if is_native else str(row["api_base_url"] or "").rstrip("/")
    health_url = (
        f"{request_origin()}/healthz"
        if is_native
        else str(row["health_url"] or "").rstrip("/")
        or derive_entry_health_url(public_url=public_url, admin_url=admin_url, api_base_url=api_url)
    )
    payload = {
        "key": entry_key,
        "label": row["label"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "sortOrder": int(row["sort_order"] or 0),
        "description": row["description"] or "",
        "publicUrl": public_url,
        "adminUrl": admin_url,
        "apiBaseUrl": api_url,
        "healthUrl": health_url,
        "embedMode": "native" if is_native else (row["embed_mode"] or "link"),
        "configured": bool(is_native or public_url or admin_url or api_url),
        "readOnly": is_native,
        "hasAdminApiKey": bool(row["admin_api_key_encrypted"]),
        "defaultAllowedGroups": json.loads(row["default_allowed_groups"] or "[]"),
        "defaultConcurrency": int(row["default_concurrency"] or 0),
        "initialBalance": float(row["initial_balance"] or 0),
        "configSource": "environment" if managed_fields else "database",
        "managedFields": managed_fields,
    }
    payload.update(provider_sync_summary(row, payload))
    if include_health:
        payload["health"] = probe_entry_provider_health(payload)
    return payload


def provider_sync_summary(row: sqlite3.Row, provider: dict[str, Any]) -> dict[str, Any]:
    entry_key = str(row["entry_key"] or "")
    if row["kind"] == "native":
        return {
            "syncMode": "native",
            "remoteSyncEnabled": True,
            "syncMessage": "Portal directly provisions Kiro upstream users.",
        }

    if entry_key == "sub2api":
        remote_sync_enabled = bool(str(row["admin_api_key_encrypted"] or "").strip() and provider_origin_url(provider))
        return {
            "syncMode": "remote_sync" if remote_sync_enabled else "local_only",
            "remoteSyncEnabled": remote_sync_enabled,
            "syncMessage": (
                "Portal will sync create, update, and delete operations to Sub2API."
                if remote_sync_enabled
                else "Portal will only manage a local subscription record until a Sub2API admin API key is configured."
            ),
        }

    return {
        "syncMode": "external",
        "remoteSyncEnabled": False,
        "syncMessage": "Portal exposes an external entry but does not provision remote users.",
    }


def probe_entry_provider_health(entry: dict[str, Any]) -> dict[str, Any]:
    if not entry.get("configured"):
        return {"reachable": False, "status": "unconfigured", "url": entry.get("healthUrl") or ""}

    health_url = str(entry.get("healthUrl") or "").strip()
    if not health_url:
        return {"reachable": False, "status": "missing_url", "url": ""}

    try:
        response = requests.get(
            health_url,
            timeout=(min(SETTINGS.connect_timeout, 5), min(SETTINGS.read_timeout, 8)),
            allow_redirects=True,
        )
        return {
            "reachable": response.status_code < 500,
            "status": "ok" if response.status_code < 500 else "error",
            "statusCode": response.status_code,
            "url": health_url,
        }
    except requests.RequestException as exc:
        return {
            "reachable": False,
            "status": "error",
            "url": health_url,
            "error": format_exception_message(exc),
        }


def parsed_url_host_port(value: str) -> tuple[str, int | None]:
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return "", None
    host = parsed.hostname or ""
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def is_private_or_loopback_host(host: str) -> bool:
    if not host:
        return False
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_private or address.is_link_local)


def probe_tcp_endpoint(host: str, port: int | None, *, timeout: float = 1.5) -> dict[str, Any]:
    if not host or port is None:
        return {"reachable": False, "host": host, "port": port, "error": "missing_target"}
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "host": host, "port": port}
    except OSError as exc:
        return {"reachable": False, "host": host, "port": port, "error": format_exception_message(exc)}


def build_entry_provider_diagnostics(row: sqlite3.Row) -> dict[str, Any]:
    provider = serialize_entry_provider(row, include_health=True)
    public_host, public_port = parsed_url_host_port(provider.get("publicUrl") or "")
    admin_host, admin_port = parsed_url_host_port(provider.get("adminUrl") or "")
    api_host, api_port = parsed_url_host_port(provider.get("apiBaseUrl") or "")
    managed_fields = provider.get("managedFields") or []

    checks: list[dict[str, Any]] = [
        {
            "label": "provider_configured",
            "ok": bool(provider.get("configured")),
            "detail": provider.get("publicUrl") or provider.get("apiBaseUrl") or provider.get("adminUrl") or "",
        },
        {
            "label": "health_probe",
            "ok": bool((provider.get("health") or {}).get("reachable")),
            "detail": (provider.get("health") or {}).get("error") or (provider.get("health") or {}).get("status"),
        },
        {
            "label": "remote_sync_ready",
            "ok": bool(provider.get("remoteSyncEnabled")),
            "detail": provider.get("syncMessage") or "",
        },
        {
            "label": "admin_api_key_present",
            "ok": bool(provider.get("hasAdminApiKey")),
            "detail": "stored" if provider.get("hasAdminApiKey") else "missing",
        },
    ]

    diagnostics: dict[str, Any] = {
        "provider": provider,
        "configSource": provider.get("configSource") or "database",
        "managedFields": managed_fields,
        "syncMode": provider.get("syncMode"),
        "checks": checks,
    }

    if str(row["entry_key"] or "") == "sub2api":
        target_host = api_host or public_host or admin_host
        target_port = api_port or public_port or admin_port
        target_is_local = is_private_or_loopback_host(target_host)
        diagnostics["runtime"] = {
            "sourceBundlePath": str(SUB2API_SOURCE_DIR),
            "sourceBundlePresent": SUB2API_SOURCE_DIR.exists(),
            "dockerAvailable": bool(shutil.which("docker")),
            "goAvailable": bool(shutil.which("go")),
            "nodeAvailable": bool(shutil.which("node")),
            "targetHost": target_host,
            "targetPort": target_port,
            "targetIsLocal": target_is_local,
            "tcpProbe": probe_tcp_endpoint(target_host, target_port) if target_is_local else {
                "reachable": None,
                "host": target_host,
                "port": target_port,
                "error": "skipped_non_local_target",
            },
        }
        diagnostics["checks"].extend(
            [
                {
                    "label": "source_bundle_present",
                    "ok": diagnostics["runtime"]["sourceBundlePresent"],
                    "detail": diagnostics["runtime"]["sourceBundlePath"],
                },
                {
                    "label": "docker_available",
                    "ok": diagnostics["runtime"]["dockerAvailable"],
                    "detail": "docker" if diagnostics["runtime"]["dockerAvailable"] else "docker_missing",
                },
                {
                    "label": "go_available",
                    "ok": diagnostics["runtime"]["goAvailable"],
                    "detail": "go" if diagnostics["runtime"]["goAvailable"] else "go_missing",
                },
            ]
        )

    return diagnostics


def validate_entry_provider_payload(row: sqlite3.Row, payload: dict[str, Any]) -> dict[str, Any]:
    is_native = row["kind"] == "native"
    label = str(payload.get("label", row["label"])).strip() or str(row["label"])
    description = str(payload.get("description", row["description"] or "")).strip()
    enabled = bool(payload.get("enabled", bool(row["enabled"])))

    if is_native:
        return {
            "label": label,
            "description": description,
            "enabled": enabled,
            "public_url": "",
            "admin_url": "",
            "api_base_url": "",
            "health_url": "",
            "admin_api_key_encrypted": row["admin_api_key_encrypted"] or "",
            "default_allowed_groups": row["default_allowed_groups"] or "[]",
            "default_concurrency": int(row["default_concurrency"] or 0),
            "initial_balance": float(row["initial_balance"] or 0),
            "embed_mode": "native",
        }

    embed_mode = str(payload.get("embedMode", row["embed_mode"] or "link")).strip().lower() or "link"
    if embed_mode not in ALLOWED_ENTRY_EMBED_MODES:
        raise PortalError("入口打开方式无效。")

    public_url = normalize_optional_url(payload.get("publicUrl", row["public_url"]))
    admin_url = normalize_optional_url(payload.get("adminUrl", row["admin_url"]))
    api_base_url = normalize_optional_url(payload.get("apiBaseUrl", row["api_base_url"]))
    health_url = normalize_optional_url(payload.get("healthUrl", row["health_url"]))
    admin_api_key = str(payload.get("adminApiKey", "") or "").strip()
    clear_admin_api_key = bool(payload.get("clearAdminApiKey"))
    default_allowed_groups = parse_optional_int_list(payload.get("defaultAllowedGroups", json.loads(row["default_allowed_groups"] or "[]")))
    default_concurrency = int(payload.get("defaultConcurrency", row["default_concurrency"] or 0))
    initial_balance = float(payload.get("initialBalance", row["initial_balance"] or 0))
    if default_concurrency < 0:
        raise PortalError("默认并发不能小于 0。")
    if initial_balance < 0:
        raise PortalError("初始余额不能小于 0。")

    return {
        "label": label,
        "description": description,
        "enabled": enabled,
        "public_url": public_url,
        "admin_url": admin_url,
        "api_base_url": api_base_url,
        "health_url": health_url,
        "admin_api_key_encrypted": (
            encrypt_data(admin_api_key)
            if admin_api_key
            else ("" if clear_admin_api_key else (row["admin_api_key_encrypted"] or ""))
        ),
        "default_allowed_groups": json.dumps(default_allowed_groups),
        "default_concurrency": default_concurrency,
        "initial_balance": initial_balance,
        "embed_mode": embed_mode,
    }


def assert_provider_update_allowed(row: sqlite3.Row, validated: dict[str, Any], payload: dict[str, Any]) -> None:
    managed_fields = set(entry_provider_managed_fields(str(row["entry_key"] or "")))
    if not managed_fields:
        return

    blocked: list[str] = []
    comparable_fields = (
        "label",
        "description",
        "enabled",
        "public_url",
        "admin_url",
        "api_base_url",
        "health_url",
        "default_allowed_groups",
        "default_concurrency",
        "initial_balance",
        "embed_mode",
    )
    for field_name in comparable_fields:
        if field_name not in managed_fields:
            continue
        current_value = row[field_name]
        if field_name == "enabled":
            current_value = bool(current_value)
        elif field_name == "default_concurrency":
            current_value = int(current_value or 0)
        elif field_name == "initial_balance":
            current_value = float(current_value or 0)
        else:
            current_value = str(current_value or "")
        if validated[field_name] != current_value:
            blocked.append(field_name)

    if "admin_api_key_encrypted" in managed_fields:
        if str(payload.get("adminApiKey", "") or "").strip() or bool(payload.get("clearAdminApiKey")):
            blocked.append("admin_api_key_encrypted")

    if blocked:
        raise PortalError(
            f"以下 Sub2API 配置项由环境变量托管，不能在后台修改: {', '.join(sorted(set(blocked)))}。",
            409,
        )


def provider_origin_url(provider: dict[str, Any]) -> str:
    api_url = str(provider.get("apiBaseUrl") or "").rstrip("/")
    if api_url.endswith("/v1"):
        return api_url[:-3].rstrip("/")
    public_url = str(provider.get("publicUrl") or "").rstrip("/")
    if public_url:
        return public_url
    admin_url = str(provider.get("adminUrl") or "").rstrip("/")
    if admin_url.endswith("/admin"):
        return admin_url[:-6].rstrip("/")
    return admin_url


def sub2api_admin_request(
    provider_row: sqlite3.Row,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    provider = serialize_entry_provider(provider_row)
    base_url = provider_origin_url(provider)
    if not base_url:
        raise PortalError("Sub2API 入口基础地址未配置。", 500)

    encrypted_key = str(provider_row["admin_api_key_encrypted"] or "").strip()
    if not encrypted_key:
        raise PortalError("Sub2API 管理 API Key 未配置。", 400)

    try:
        admin_api_key = decrypt_data(encrypted_key)
    except Exception as exc:
        raise PortalError("Sub2API 管理 API Key 解密失败。", 500) from exc

    url = f"{base_url}{path}"
    headers = {"x-api-key": admin_api_key}
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=(SETTINGS.connect_timeout, SETTINGS.read_timeout),
        )
    except requests.RequestException as exc:
        raise PortalError(f"Sub2API 请求失败: {format_exception_message(exc)}", 502) from exc

    payload: dict[str, Any] = {}
    if response.text.strip():
        try:
            payload = response.json()
        except ValueError:
            payload = {}

    if response.status_code >= 400:
        message = payload.get("message") or payload.get("error") or response.text.strip() or f"HTTP {response.status_code}"
        raise PortalError(f"Sub2API 返回错误: {message}", response.status_code if response.status_code < 500 else 502)

    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if payload else {}


def plan_defaults(plan_key: str) -> dict[str, Any]:
    return PLAN_PROFILES.get(plan_key, PLAN_PROFILES["starter"])


def quota_cards(row: sqlite3.Row) -> list[dict[str, Any]]:
    plan = plan_defaults(row["plan_key"])
    return [
        {"label": "套餐", "value": plan["label"], "detail": plan["description"]},
        {"label": "每日额度", "value": f'{row["daily_quota"]:,}', "detail": "每日 token 上限"},
        {"label": "月度额度", "value": f'{row["monthly_quota"]:,}', "detail": "月累计 token 上限"},
        {"label": "请求次数", "value": f'{row["request_quota"]:,}', "detail": "单月请求数限制"},
        {"label": "速率限制", "value": f'{row["rate_limit_rpm"]} RPM', "detail": "每分钟请求数限制"},
    ]


def normalize_daily_usage(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in items or []:
        label = str(item.get("date") or item.get("day") or item.get("label") or "")[:10]
        if not label:
            continue
        requests_count = int(
            item.get("requests")
            or item.get("request_count")
            or item.get("total_requests")
            or item.get("count")
            or 0
        )
        token_count = int(
            item.get("tokens")
            or item.get("token_count")
            or item.get("total_tokens")
            or item.get("usage")
            or 0
        )
        lookup[label] = {
            "label": label[5:] if len(label) >= 10 else label,
            "date": label,
            "count": requests_count,
            "tokens": token_count,
        }

    start = now_utc().date() - timedelta(days=6)
    series: list[dict[str, Any]] = []
    for offset in range(7):
        current = start + timedelta(days=offset)
        key = current.isoformat()
        series.append(lookup.get(key, {"label": key[5:], "date": key, "count": 0, "tokens": 0}))
    return series


def create_session(conn: sqlite3.Connection, role: str, subject_id: int, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM portal_sessions WHERE role = ? AND subject_id = ?", (role, subject_id))
    conn.execute(
        """
        INSERT INTO portal_sessions (token, role, subject_id, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            token,
            role,
            subject_id,
            isoformat(),
            isoformat(now_utc() + timedelta(hours=hours)),
        ),
    )
    conn.commit()
    return token


def cookie_name_for_role(role: str) -> str:
    return ADMIN_COOKIE if role == "admin" else USER_COOKIE


def get_subject_from_session(role: str, table: str) -> sqlite3.Row | None:
    token = request.cookies.get(cookie_name_for_role(role))
    if not token:
        return None

    with open_db() as conn:
        session_row = conn.execute(
            "SELECT * FROM portal_sessions WHERE token = ? AND role = ?",
            (token, role),
        ).fetchone()
        if not session_row:
            return None
        if parse_iso(session_row["expires_at"]) <= now_utc():
            conn.execute("DELETE FROM portal_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (session_row["subject_id"],)).fetchone()


def require_user() -> sqlite3.Row:
    user = get_subject_from_session("user", "portal_users")
    if not user or not bool(user["enabled"]):
        raise PortalError("请先登录。", 401)
    return user


def require_admin() -> sqlite3.Row:
    admin = get_subject_from_session("admin", "portal_admins")
    if not admin or not bool(admin["enabled"]):
        raise PortalError("请先以管理员身份登录。", 401)
    return admin


def set_session_cookie(response: Response, role: str, token: str | None) -> None:
    cookie_name = cookie_name_for_role(role)
    if token:
        ttl = SETTINGS.admin_session_hours if role == "admin" else SETTINGS.user_session_hours
        response.set_cookie(
            cookie_name,
            token,
            httponly=True,
            secure=SETTINGS.cookie_secure,
            samesite="Lax",
            max_age=ttl * 3600,
            path="/",
        )
        return
    response.set_cookie(cookie_name, "", expires=0, max_age=0, httponly=True, secure=SETTINGS.cookie_secure, samesite="Lax", path="/")


def delete_session_for_request(role: str) -> None:
    token = request.cookies.get(cookie_name_for_role(role))
    if not token:
        return
    with open_db() as conn:
        conn.execute("DELETE FROM portal_sessions WHERE token = ?", (token,))
        conn.commit()


def clear_subject_sessions(conn: sqlite3.Connection, role: str, subject_id: int) -> None:
    conn.execute("DELETE FROM portal_sessions WHERE role = ? AND subject_id = ?", (role, subject_id))
    conn.commit()


def parse_json_body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def upstream_admin_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    if not SETTINGS.upstream_admin_password:
        raise PortalError("尚未配置上游管理员口令。请设置 RELAY_UPSTREAM_ADMIN_PASSWORD。", 500)

    url = f"{SETTINGS.upstream_url}{path}"
    headers = {"Authorization": f"Bearer {SETTINGS.upstream_admin_password}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=(SETTINGS.connect_timeout, SETTINGS.read_timeout),
        )
    except requests.RequestException as exc:
        raise UpstreamUnavailableError(str(exc)) from exc

    if response.status_code >= 400:
        message = response.text.strip() or f"HTTP {response.status_code}"
        try:
            payload = response.json()
            message = payload.get("error") or payload.get("message") or message
        except ValueError:
            pass
        status_code = 502 if response.status_code >= 500 else response.status_code
        raise PortalError(f"上游返回错误: {message}", status_code)

    if not response.text.strip():
        return {}
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type.lower():
        return response.json()
    return {"message": response.text.strip()}


def unix_timestamp(value: datetime | None = None) -> int:
    current = value or now_utc()
    return int(current.timestamp())


def generated_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


def filtered_proxy_headers(*, content_type: str | None = None, accept: str | None = None) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept
    return headers


def response_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type in {"input_text", "output_text", "text"}:
            text = item.get("text")
            if text:
                parts.append(str(text))
        elif item_type == "refusal":
            refusal = item.get("refusal")
            if refusal:
                parts.append(str(refusal))
        elif item_type in {"input_image", "image"}:
            image_url = item.get("image_url") or item.get("url") or item.get("file_id")
            if image_url:
                parts.append(f"[image:{image_url}]")
    return "".join(parts)


def response_output_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def response_input_to_chat_messages(input_payload: Any, instructions: str | None = None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})

    if isinstance(input_payload, str):
        return [*messages, {"role": "user", "content": input_payload}]
    if isinstance(input_payload, dict):
        items = [input_payload]
    elif isinstance(input_payload, list):
        items = input_payload
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type == "message":
            role = str(item.get("role") or "user").lower()
            role = "system" if role == "developer" else role
            content = response_content_text(item.get("content"))
            if content or role in {"system", "user"}:
                messages.append({"role": role, "content": content})
            continue
        if item_type == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or generated_id("call"))
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": str(item.get("name") or ""),
                                "arguments": str(item.get("arguments") or "{}"),
                            },
                        }
                    ],
                }
            )
            continue
        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or item.get("id") or "")
            if call_id:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": response_output_value(item.get("output")),
                    }
                )
            continue
    return messages


def responses_request_to_chat_request(payload: dict[str, Any]) -> dict[str, Any]:
    chat_payload: dict[str, Any] = {
        "model": payload.get("model") or "gpt-5.4",
        "messages": response_input_to_chat_messages(payload.get("input"), str(payload.get("instructions") or "").strip() or None),
    }

    if isinstance(payload.get("tools"), list):
        chat_payload["tools"] = payload["tools"]
    if payload.get("tool_choice") is not None:
        chat_payload["tool_choice"] = payload["tool_choice"]
    if payload.get("parallel_tool_calls") is not None:
        chat_payload["parallel_tool_calls"] = bool(payload["parallel_tool_calls"])
    if payload.get("temperature") is not None:
        chat_payload["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        chat_payload["top_p"] = payload["top_p"]
    if payload.get("max_output_tokens") is not None:
        chat_payload["max_tokens"] = payload["max_output_tokens"]
    if payload.get("metadata") is not None:
        chat_payload["metadata"] = payload["metadata"]
    return chat_payload


def chat_content_chunks(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []

    chunks: list[str] = []
    for item in value:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if text:
            chunks.append(str(text))
    return chunks


def chat_message_text(message: dict[str, Any]) -> str:
    return "".join(chat_content_chunks(message.get("content")))


def responses_usage_from_chat(usage_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(usage_payload, dict):
        return None

    prompt_tokens = int(usage_payload.get("prompt_tokens") or 0)
    completion_tokens = int(usage_payload.get("completion_tokens") or 0)
    total_tokens = int(usage_payload.get("total_tokens") or (prompt_tokens + completion_tokens))
    return {
        "input_tokens": prompt_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": completion_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": total_tokens,
    }


def response_message_item(item_id: str, text: str, *, status: str) -> dict[str, Any]:
    if status == "in_progress":
        return {"id": item_id, "type": "message", "status": status, "role": "assistant", "content": []}
    return {
        "id": item_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [{"type": "output_text", "annotations": [], "logprobs": [], "text": text}],
    }


def response_function_item(item_id: str, *, status: str, name: str, arguments: str, call_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "function_call",
        "status": status,
        "name": name,
        "arguments": arguments,
        "call_id": call_id,
    }


def response_object_payload(
    request_payload: dict[str, Any],
    response_id: str,
    created_at: int,
    *,
    status: str,
    output: list[dict[str, Any]],
    completed_at: int | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response_payload: dict[str, Any] = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "background": False,
        "completed_at": completed_at,
        "error": None,
        "incomplete_details": None,
        "instructions": request_payload.get("instructions"),
        "model": request_payload.get("model") or "gpt-5.4",
        "output": output,
        "parallel_tool_calls": bool(request_payload.get("parallel_tool_calls", True)),
        "tool_choice": request_payload.get("tool_choice", "auto"),
        "tools": payload_tools if isinstance((payload_tools := request_payload.get("tools")), list) else [],
        "store": False,
        "text": request_payload.get("text") or {"format": {"type": "text"}},
    }
    if usage:
        response_payload["usage"] = usage
    return response_payload


def response_outputs_from_chat_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    text = chat_message_text(message)
    if text:
        outputs.append(response_message_item(generated_id("msg"), text, status="completed"))
    for tool_call in message.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        function_payload = tool_call.get("function") or {}
        outputs.append(
            response_function_item(
                generated_id("fc"),
                status="completed",
                name=str(function_payload.get("name") or ""),
                arguments=str(function_payload.get("arguments") or "{}"),
                call_id=str(tool_call.get("id") or generated_id("call")),
            )
        )
    if not outputs:
        outputs.append(response_message_item(generated_id("msg"), "", status="completed"))
    return outputs


def responses_json_from_chat(request_payload: dict[str, Any], chat_payload: dict[str, Any]) -> dict[str, Any]:
    choices = chat_payload.get("choices") or []
    message = ((choices[0] or {}).get("message") if choices else {}) or {}
    created_at = int(chat_payload.get("created") or unix_timestamp())
    return response_object_payload(
        request_payload,
        generated_id("resp"),
        created_at,
        status="completed",
        output=response_outputs_from_chat_message(message),
        completed_at=unix_timestamp(),
        usage=responses_usage_from_chat(chat_payload.get("usage")),
    )


def sse_data(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def stream_chat_completion_as_responses(upstream: requests.Response, request_payload: dict[str, Any]) -> Response:
    response_id = generated_id("resp")
    created_at = unix_timestamp()
    sequence_number = 1
    output_index = 0
    usage_payload: dict[str, Any] | None = None
    message_state: dict[str, Any] | None = None
    tool_states: dict[int, dict[str, Any]] = {}

    def next_sequence() -> int:
        nonlocal sequence_number
        current = sequence_number
        sequence_number += 1
        return current

    def tool_state(index: int, tool_delta: dict[str, Any]) -> dict[str, Any]:
        nonlocal output_index
        state = tool_states.get(index)
        if state is None:
            function_payload = tool_delta.get("function") or {}
            state = {
                "item_id": generated_id("fc"),
                "output_index": output_index,
                "call_id": str(tool_delta.get("id") or generated_id("call")),
                "name": str(function_payload.get("name") or ""),
                "arguments": "",
                "done": False,
            }
            output_index += 1
            tool_states[index] = state
        return state

    def ensure_message_state() -> dict[str, Any]:
        nonlocal message_state, output_index
        if message_state is None:
            message_state = {
                "item_id": generated_id("msg"),
                "output_index": output_index,
                "text": "",
                "done": False,
            }
            output_index += 1
        return message_state

    def finalize_message_events() -> list[str]:
        if not message_state or message_state["done"]:
            return []
        state = message_state
        state["done"] = True
        text = str(state["text"])
        return [
            sse_data(
                {
                    "type": "response.output_text.done",
                    "content_index": 0,
                    "item_id": state["item_id"],
                    "logprobs": [],
                    "output_index": state["output_index"],
                    "sequence_number": next_sequence(),
                    "text": text,
                }
            ),
            sse_data(
                {
                    "type": "response.content_part.done",
                    "content_index": 0,
                    "item_id": state["item_id"],
                    "output_index": state["output_index"],
                    "part": {"type": "output_text", "annotations": [], "logprobs": [], "text": text},
                    "sequence_number": next_sequence(),
                }
            ),
            sse_data(
                {
                    "type": "response.output_item.done",
                    "item": response_message_item(state["item_id"], text, status="completed"),
                    "output_index": state["output_index"],
                    "sequence_number": next_sequence(),
                }
            ),
        ]

    def finalize_tool_events() -> list[str]:
        events: list[str] = []
        for index in sorted(tool_states):
            state = tool_states[index]
            if state["done"]:
                continue
            state["done"] = True
            events.extend(
                [
                    sse_data(
                        {
                            "type": "response.function_call_arguments.done",
                            "arguments": state["arguments"],
                            "item_id": state["item_id"],
                            "output_index": state["output_index"],
                            "sequence_number": next_sequence(),
                        }
                    ),
                    sse_data(
                        {
                            "type": "response.output_item.done",
                            "item": response_function_item(
                                state["item_id"],
                                status="completed",
                                name=state["name"],
                                arguments=state["arguments"],
                                call_id=state["call_id"],
                            ),
                            "output_index": state["output_index"],
                            "sequence_number": next_sequence(),
                        }
                    ),
                ]
            )
        return events

    def finalized_output() -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        if message_state:
            output.append((message_state["output_index"], response_message_item(message_state["item_id"], str(message_state["text"]), status="completed")))
        for state in tool_states.values():
            output.append(
                (
                    state["output_index"],
                    response_function_item(
                        state["item_id"],
                        status="completed",
                        name=state["name"],
                        arguments=state["arguments"],
                        call_id=state["call_id"],
                    ),
                )
            )
        output.sort(key=lambda item: item[0])
        return [item for _, item in output]

    def event_stream():
        try:
            yield sse_data(
                {
                    "type": "response.created",
                    "response": response_object_payload(
                        request_payload,
                        response_id,
                        created_at,
                        status="in_progress",
                        output=[],
                        completed_at=None,
                    ),
                }
            )

            for raw_line in upstream.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break

                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if isinstance(payload.get("usage"), dict):
                    usage_payload = payload["usage"]

                for choice in payload.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta") or {}

                    for text_chunk in chat_content_chunks(delta.get("content")):
                        state = ensure_message_state()
                        if state["text"] == "":
                            yield sse_data(
                                {
                                    "type": "response.output_item.added",
                                    "item": response_message_item(state["item_id"], "", status="in_progress"),
                                    "output_index": state["output_index"],
                                    "sequence_number": next_sequence(),
                                }
                            )
                            yield sse_data(
                                {
                                    "type": "response.content_part.added",
                                    "content_index": 0,
                                    "item_id": state["item_id"],
                                    "output_index": state["output_index"],
                                    "part": {"type": "output_text", "annotations": [], "logprobs": [], "text": ""},
                                    "sequence_number": next_sequence(),
                                }
                            )
                        state["text"] += text_chunk
                        yield sse_data(
                            {
                                "type": "response.output_text.delta",
                                "content_index": 0,
                                "delta": text_chunk,
                                "item_id": state["item_id"],
                                "logprobs": [],
                                "output_index": state["output_index"],
                                "sequence_number": next_sequence(),
                            }
                        )

                    for tool_delta in delta.get("tool_calls") or []:
                        if not isinstance(tool_delta, dict):
                            continue
                        index = int(tool_delta.get("index") or 0)
                        state = tool_state(index, tool_delta)
                        function_payload = tool_delta.get("function") or {}

                        if not state.get("added"):
                            yield sse_data(
                                {
                                    "type": "response.output_item.added",
                                    "item": response_function_item(
                                        state["item_id"],
                                        status="in_progress",
                                        name=state["name"],
                                        arguments=state["arguments"],
                                        call_id=state["call_id"],
                                    ),
                                    "output_index": state["output_index"],
                                    "sequence_number": next_sequence(),
                                }
                            )
                            state["added"] = True

                        if tool_delta.get("id"):
                            state["call_id"] = str(tool_delta["id"])
                        if function_payload.get("name"):
                            state["name"] = str(function_payload["name"])
                        if function_payload.get("arguments"):
                            state["arguments"] += str(function_payload["arguments"])
                            yield sse_data(
                                {
                                    "type": "response.function_call_arguments.delta",
                                    "delta": str(function_payload["arguments"]),
                                    "item_id": state["item_id"],
                                    "output_index": state["output_index"],
                                    "sequence_number": next_sequence(),
                                }
                            )

                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        for event in finalize_message_events():
                            yield event
                        for event in finalize_tool_events():
                            yield event

            for event in finalize_message_events():
                yield event
            for event in finalize_tool_events():
                yield event

            yield sse_data(
                {
                    "type": "response.completed",
                    "response": response_object_payload(
                        request_payload,
                        response_id,
                        created_at,
                        status="completed",
                        output=finalized_output(),
                        completed_at=unix_timestamp(),
                        usage=responses_usage_from_chat(usage_payload),
                    ),
                }
            )
            yield sse_data("[DONE]")
        finally:
            upstream.close()

    return Response(
        stream_with_context(event_stream()),
        status=200,
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def upstream_responses_compat() -> Response:
    payload = parse_json_body()
    chat_payload = responses_request_to_chat_request(payload)
    stream = bool(payload.get("stream", False))
    headers = filtered_proxy_headers(content_type="application/json", accept="text/event-stream" if stream else "application/json")
    target_url = f"{SETTINGS.upstream_url}/v1/chat/completions"

    try:
        upstream = requests.post(
            target_url,
            headers=headers,
            params=request.args,
            json={**chat_payload, "stream": stream},
            stream=stream,
            timeout=(SETTINGS.connect_timeout, SETTINGS.read_timeout),
        )
    except requests.RequestException as exc:
        raise UpstreamUnavailableError(f"Responses 兼容层请求失败: {exc}") from exc

    if not stream:
        forwarded_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        if upstream.status_code >= 400:
            body = upstream.content
            upstream.close()
            return Response(body, status=upstream.status_code, headers=forwarded_headers)
        try:
            chat_response = upstream.json()
        finally:
            upstream.close()
        return jsonify(responses_json_from_chat(payload, chat_response))

    if upstream.status_code >= 400 or "text/event-stream" not in upstream.headers.get("Content-Type", "").lower():
        forwarded_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        body = upstream.content
        upstream.close()
        return Response(body, status=upstream.status_code, headers=forwarded_headers)

    return stream_chat_completion_as_responses(upstream, payload)


def upstream_proxy_response(subpath: str) -> Response:
    target_url = f"{SETTINGS.upstream_url}/v1/{subpath}"
    headers = filtered_proxy_headers()

    try:
        upstream = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            stream=True,
            timeout=(SETTINGS.connect_timeout, SETTINGS.read_timeout),
        )
    except requests.RequestException as exc:
        raise UpstreamUnavailableError(f"API 代理失败: {exc}") from exc

    forwarded_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    if "text/event-stream" in upstream.headers.get("Content-Type", "").lower():
        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        return Response(stream_with_context(generate()), status=upstream.status_code, headers=forwarded_headers)

    body = upstream.content
    upstream.close()
    return Response(body, status=upstream.status_code, headers=forwarded_headers)


def upstream_user_list() -> list[dict[str, Any]]:
    payload = upstream_admin_request("GET", "/v2/users")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("users"), list):
        return payload["users"]
    return []


def find_local_user_by_public_id(public_id: str) -> sqlite3.Row:
    with open_db() as conn:
        row = conn.execute("SELECT * FROM portal_users WHERE public_id = ?", (public_id,)).fetchone()
    if not row:
        raise PortalError("用户不存在。", 404)
    return row


def serialize_portal_user(
    row: sqlite3.Row,
    *,
    include_api_key: bool = True,
    upstream: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upstream = upstream or {}
    provider = provider or serialize_entry_provider_by_key(str(row["provider_key"] or "kiro"))
    plan = plan_defaults(row["plan_key"])
    provider_key = str(row["provider_key"] or "kiro")
    is_kiro = provider_key == "kiro"
    return {
        "id": row["public_id"],
        "workspace": row["workspace"],
        "email": row["email"],
        "plan": row["plan_key"],
        "planLabel": plan["label"],
        "providerKey": provider_key,
        "providerLabel": provider.get("label") or provider_key,
        "usecase": row["usecase"],
        "notes": row["notes"],
        "enabled": bool(row["enabled"]),
        "apiKey": (row["upstream_api_key"] if include_api_key else "****") if is_kiro else "",
        "baseUrl": provider.get("apiBaseUrl") or (api_base_url() if is_kiro else ""),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "dailyQuota": row["daily_quota"],
        "monthlyQuota": row["monthly_quota"],
        "requestQuota": row["request_quota"],
        "rateLimitRpm": row["rate_limit_rpm"],
        "upstreamUserId": row["upstream_user_id"],
        "entry": provider,
        "upstreamTotals": {
            "totalRequests": int(upstream.get("total_requests") or 0),
            "dailyRequests": int(upstream.get("daily_requests") or 0),
            "totalTokens": int(upstream.get("total_tokens_used") or 0),
            "totalCostUsd": float(upstream.get("total_cost_usd") or 0),
        },
    }


def build_user_dashboard(row: sqlite3.Row) -> dict[str, Any]:
    provider = serialize_entry_provider_by_key(str(row["provider_key"] or "kiro"))
    if str(row["provider_key"] or "kiro") != "kiro":
        empty_usage = normalize_daily_usage([])
        return {
            "user": serialize_portal_user(row, provider=provider),
            "metrics": {
                "requests30d": 0,
                "tokens30d": 0,
                "todayRequests": 0,
                "todayTokens": 0,
                "quotaRemaining": row["monthly_quota"],
                "monthlyCostUsd": 0,
            },
            "daily": empty_usage,
        "quotas": quota_cards(row),
        "externalEntry": {
            "provider": provider,
            "message": "该套餐通过外部入口交付，请使用对应入口继续。",
        },
        }

    stats = upstream_admin_request("GET", f"/v2/users/{row['upstream_user_id']}/stats", params={"days": 30})
    usage_series = normalize_daily_usage(stats.get("daily_usage") if isinstance(stats, dict) else [])
    total_requests = int(stats.get("total_requests") or 0)
    total_tokens = int(stats.get("total_tokens") or 0)
    quota_remaining = int(stats.get("quota_remaining") or row["monthly_quota"])
    total_cost = float(stats.get("total_cost_usd") or stats.get("monthly_cost_usd") or 0)
    latest_day = usage_series[-1] if usage_series else {"count": 0, "tokens": 0}

    return {
        "user": serialize_portal_user(row, provider=provider),
        "metrics": {
            "requests30d": total_requests,
            "tokens30d": total_tokens,
            "todayRequests": int(latest_day["count"]),
            "todayTokens": int(latest_day["tokens"]),
            "quotaRemaining": quota_remaining,
            "monthlyCostUsd": round(total_cost, 4),
        },
        "daily": usage_series,
        "quotas": quota_cards(row),
    }


def provider_user_counts() -> dict[str, int]:
    with open_db() as conn:
        rows = conn.execute(
            "SELECT provider_key, COUNT(*) AS count FROM portal_users GROUP BY provider_key"
        ).fetchall()
    return {str(row["provider_key"] or "kiro"): int(row["count"] or 0) for row in rows}


def validate_user_payload(payload: dict[str, Any], *, require_password: bool) -> dict[str, Any]:
    workspace = str(payload.get("workspace", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    plan_key = str(payload.get("plan", "starter")).strip().lower()
    provider_key = str(payload.get("providerKey", payload.get("provider", "kiro"))).strip().lower() or "kiro"
    usecase = str(payload.get("usecase", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    enabled = bool(payload.get("enabled", True))

    if not workspace or len(workspace) < 2:
        raise PortalError("工作区名称至少需要 2 个字符。")
    if not email or "@" not in email:
        raise PortalError("请输入有效邮箱。")
    if require_password and len(password) < 8:
        raise PortalError("密码至少需要 8 位。")
    if plan_key not in PLAN_PROFILES:
        plan_key = "starter"
    if provider_key not in ENTRY_PROVIDERS:
        provider_key = "kiro"

    profile = plan_defaults(plan_key)
    daily_quota = int(payload.get("dailyQuota") or profile["daily_quota"])
    monthly_quota = int(payload.get("monthlyQuota") or profile["monthly_quota"])
    request_quota = int(payload.get("requestQuota") or profile["request_quota"])
    rate_limit_rpm = int(payload.get("rateLimitRpm") or profile["rate_limit_rpm"])

    if min(daily_quota, monthly_quota, request_quota, rate_limit_rpm) < 0:
        raise PortalError("额度和限速不能为负数。")

    return {
        "workspace": workspace,
        "email": email,
        "password": password,
        "plan_key": plan_key,
        "provider_key": provider_key,
        "usecase": usecase,
        "notes": notes,
        "enabled": enabled,
        "daily_quota": daily_quota,
        "monthly_quota": monthly_quota,
        "request_quota": request_quota,
        "rate_limit_rpm": rate_limit_rpm,
    }


def provider_available_for_public_signup(provider: dict[str, Any]) -> bool:
    if provider.get("key") == "kiro":
        return True
    return bool(provider.get("enabled") and provider.get("configured"))


def create_local_user(payload: dict[str, Any], *, actor: str = "admin") -> sqlite3.Row:
    validated = validate_user_payload(payload, require_password=True)
    now = isoformat()
    provider_key = validated["provider_key"]

    with open_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM portal_users WHERE workspace = ? OR email = ?",
            (validated["workspace"], validated["email"]),
        ).fetchone()
        if existing:
            raise PortalError("工作区或邮箱已经存在。", 409)

    public_id = secrets.token_hex(12)
    provider = serialize_entry_provider_by_key(provider_key)
    if actor == "public" and not provider_available_for_public_signup(provider):
        raise PortalError(f"{provider.get('label') or provider_key} 当前未开放注册。", 403)
    if provider_key != "kiro" and not provider.get("configured"):
        raise PortalError(f"{provider.get('label') or provider_key} 入口尚未配置。", 400)

    provider_row = find_entry_provider_row(provider_key)
    upstream_user = None
    upstream_user_id = f"{provider_key}:{public_id}"
    upstream_api_key = ""
    if provider_key == "kiro":
        upstream_user = upstream_admin_request(
            "POST",
            "/v2/users",
            json_body={
                "name": validated["workspace"],
                "daily_quota": validated["daily_quota"],
                "monthly_quota": validated["monthly_quota"],
                "request_quota": validated["request_quota"],
                "rate_limit_rpm": validated["rate_limit_rpm"],
                "enabled": validated["enabled"],
                "is_vip": False,
                "notes": validated["notes"] or validated["usecase"] or "Portal registration",
            },
        )
        upstream_user_id = upstream_user["id"]
        upstream_api_key = upstream_user["api_key"]
    elif provider_key == "sub2api":
        if str(provider_row["admin_api_key_encrypted"] or "").strip():
            upstream_user = sub2api_admin_request(
                provider_row,
                "POST",
                "/api/v1/admin/users",
                json_body={
                    "email": validated["email"],
                    "password": validated["password"],
                    "username": validated["workspace"],
                    "notes": validated["notes"] or validated["usecase"] or "Portal registration",
                    "balance": float(provider_row["initial_balance"] or 0),
                    "concurrency": int(provider_row["default_concurrency"] or 0),
                    "allowed_groups": json.loads(provider_row["default_allowed_groups"] or "[]"),
                },
            )
            upstream_user_id = str(upstream_user["id"])

    try:
        with open_db() as conn:
            conn.execute(
                """
                INSERT INTO portal_users (
                    public_id, workspace, email, password_hash, plan_key, usecase, notes, enabled,
                    upstream_user_id, upstream_api_key, provider_key, daily_quota, monthly_quota, request_quota,
                    rate_limit_rpm, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    public_id,
                    validated["workspace"],
                    validated["email"],
                    password_hash(validated["password"]),
                    validated["plan_key"],
                    validated["usecase"],
                    validated["notes"],
                    1 if validated["enabled"] else 0,
                    upstream_user_id,
                    upstream_api_key,
                    provider_key,
                    validated["daily_quota"],
                    validated["monthly_quota"],
                    validated["request_quota"],
                    validated["rate_limit_rpm"],
                    now,
                    now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT * FROM portal_users WHERE public_id = ?", (public_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        if upstream_user and provider_key == "kiro":
            try:
                upstream_admin_request("DELETE", f"/v2/users/{upstream_user['id']}")
            except PortalError:
                pass
        if upstream_user and provider_key == "sub2api":
            try:
                sub2api_admin_request(provider_row, "DELETE", f"/api/v1/admin/users/{upstream_user['id']}")
            except PortalError:
                pass
        raise PortalError("本地用户写入失败，请重试。", 500) from exc


def bootstrap_admin(email: str, password: str, display_name: str) -> tuple[str, int]:
    normalized_email = email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise PortalError("管理员邮箱格式无效。")
    if len(password) < 10:
        raise PortalError("管理员密码至少需要 10 位。")

    current_time = isoformat()
    with open_db() as conn:
        existing = conn.execute("SELECT * FROM portal_admins WHERE email = ?", (normalized_email,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE portal_admins
                SET display_name = ?, password_hash = ?, enabled = 1, updated_at = ?
                WHERE id = ?
                """,
                (display_name, password_hash(password), current_time, existing["id"]),
            )
            conn.commit()
            return "updated", existing["id"]

        cursor = conn.execute(
            """
            INSERT INTO portal_admins (email, display_name, password_hash, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (normalized_email, display_name, password_hash(password), current_time, current_time),
        )
        conn.commit()
        return "created", int(cursor.lastrowid)


def maybe_bootstrap_admin_from_env() -> None:
    if SETTINGS.bootstrap_admin_email and SETTINGS.bootstrap_admin_password:
        bootstrap_admin(
            SETTINGS.bootstrap_admin_email,
            SETTINGS.bootstrap_admin_password,
            SETTINGS.bootstrap_admin_name,
        )


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(ASSET_DIR), static_url_path="/assets")
    app.config["JSON_AS_ASCII"] = False
    app.secret_key = SETTINGS.session_secret

    @app.errorhandler(PortalError)
    def handle_portal_error(error: PortalError):
        return jsonify({"error": error.message}), error.status_code

    @app.errorhandler(404)
    def handle_not_found(_error):
        if request.path.startswith("/api/") or request.path.startswith("/v1/"):
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(BASE_DIR, "index.html")

    @app.after_request
    def add_headers(response: Response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.path == "/healthz" or request.path.startswith("/v1/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        return response

    @app.route("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/registration-manager")
    def registration_manager():
        require_admin()
        return send_from_directory(ASSET_DIR, "registration-manager.html")

    @app.get("/api/config")
    def config_payload():
        providers = [serialize_entry_provider(row) for row in list_entry_provider_rows()]
        return jsonify(
            {
                "portalBaseUrl": portal_base_url(),
                "apiBaseUrl": api_base_url(),
                "adminBaseUrl": admin_base_url(),
                "upstreamUrl": SETTINGS.upstream_url,
                "cookieSecure": SETTINGS.cookie_secure,
                "providers": providers,
            }
        )

    @app.get("/healthz")
    def healthz():
        providers = [serialize_entry_provider(row, include_health=True) for row in list_entry_provider_rows()]
        health = {
            "status": "ok",
            "time": isoformat(),
            "portal": {"dbPath": str(DB_PATH), "baseUrl": portal_base_url()},
            "entries": providers,
        }
        try:
            settings = upstream_admin_request("GET", "/v2/settings")
            health["upstream"] = {
                "reachable": True,
                "edition": settings.get("edition"),
                "version": settings.get("version"),
                "currentAccountCount": settings.get("currentAccountCount"),
            }
        except PortalError as exc:
            health["status"] = "degraded"
            health["upstream"] = {"reachable": False, "error": exc.message}
        return jsonify(health)

    @app.get("/v1/models")
    def compat_models():
        created_at = unix_timestamp()
        return jsonify(
            {
                "object": "list",
                "data": [
                    {"id": "gpt-5.4", "object": "model", "created": created_at, "owned_by": "relay"},
                    {"id": "gpt-5.3-codex", "object": "model", "created": created_at, "owned_by": "relay"},
                ],
            }
        )

    @app.route("/v1/responses", methods=["POST", "OPTIONS"])
    def compat_responses():
        if request.method == "OPTIONS":
            return Response(status=204)
        return upstream_responses_compat()

    @app.route("/v1/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def proxy_v1(subpath: str):
        if request.method == "OPTIONS":
            return Response(status=204)
        return upstream_proxy_response(subpath)

    @app.post("/api/auth/register")
    def user_register():
        row = create_local_user(parse_json_body(), actor="public")
        with open_db() as conn:
            token = create_session(conn, "user", row["id"], SETTINGS.user_session_hours)
        payload = build_user_dashboard(row)
        response = make_response(jsonify(payload), 201)
        set_session_cookie(response, "user", token)
        return response

    @app.post("/api/auth/login")
    def user_login():
        payload = parse_json_body()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        with open_db() as conn:
            row = conn.execute("SELECT * FROM portal_users WHERE email = ?", (email,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                raise PortalError("邮箱或密码错误。", 401)
            if not bool(row["enabled"]):
                raise PortalError("该用户已被禁用。", 403)
            token = create_session(conn, "user", row["id"], SETTINGS.user_session_hours)
            conn.execute("UPDATE portal_users SET last_login_at = ?, updated_at = ? WHERE id = ?", (isoformat(), isoformat(), row["id"]))
            conn.commit()
            refreshed = conn.execute("SELECT * FROM portal_users WHERE id = ?", (row["id"],)).fetchone()
        response = make_response(jsonify(build_user_dashboard(refreshed)))
        set_session_cookie(response, "user", token)
        return response

    @app.post("/api/auth/logout")
    def user_logout():
        delete_session_for_request("user")
        response = make_response(jsonify({"ok": True}))
        set_session_cookie(response, "user", None)
        return response

    @app.get("/api/auth/me")
    def user_me():
        row = require_user()
        return jsonify({"user": serialize_portal_user(row)})

    @app.get("/api/dashboard")
    def user_dashboard():
        row = require_user()
        return jsonify(build_user_dashboard(row))

    @app.post("/api/apikey/rotate")
    def rotate_user_api_key():
        row = require_user()
        if str(row["provider_key"] or "kiro") != "kiro":
            raise PortalError("当前套餐不使用 Kiro API Key，请通过对应入口使用服务。", 400)
        upstream = upstream_admin_request("POST", f"/v2/users/{row['upstream_user_id']}/regenerate-key")
        with open_db() as conn:
            conn.execute(
                "UPDATE portal_users SET upstream_api_key = ?, updated_at = ? WHERE id = ?",
                (upstream["api_key"], isoformat(), row["id"]),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM portal_users WHERE id = ?", (row["id"],)).fetchone()
        return jsonify(build_user_dashboard(refreshed))

    @app.post("/api/admin/login")
    def admin_login():
        payload = parse_json_body()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        with open_db() as conn:
            row = conn.execute("SELECT * FROM portal_admins WHERE email = ?", (email,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                raise PortalError("管理员邮箱或密码错误。", 401)
            if not bool(row["enabled"]):
                raise PortalError("管理员账号已被禁用。", 403)
            token = create_session(conn, "admin", row["id"], SETTINGS.admin_session_hours)
            conn.execute("UPDATE portal_admins SET last_login_at = ?, updated_at = ? WHERE id = ?", (isoformat(), isoformat(), row["id"]))
            conn.commit()
            refreshed = conn.execute("SELECT * FROM portal_admins WHERE id = ?", (row["id"],)).fetchone()
        response = make_response(
            jsonify(
                {
                    "admin": {
                        "email": refreshed["email"],
                        "displayName": refreshed["display_name"],
                        "createdAt": refreshed["created_at"],
                    }
                }
            )
        )
        set_session_cookie(response, "admin", token)
        return response

    @app.post("/api/admin/logout")
    def admin_logout():
        delete_session_for_request("admin")
        response = make_response(jsonify({"ok": True}))
        set_session_cookie(response, "admin", None)
        return response

    @app.get("/api/admin/me")
    def admin_me():
        row = require_admin()
        return jsonify({"admin": {"email": row["email"], "displayName": row["display_name"], "createdAt": row["created_at"]}})

    @app.get("/api/admin/overview")
    def admin_overview():
        require_admin()
        with open_db() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS user_count,
                    SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled_user_count
                FROM portal_users
                """
            ).fetchone()
            admin_count = conn.execute("SELECT COUNT(*) AS count FROM portal_admins").fetchone()["count"]

        provider_counts = provider_user_counts()
        upstream_payload = {
            "reachable": False,
            "edition": None,
            "version": None,
            "currentAccountCount": 0,
            "accountSelectionMode": None,
            "enableRequestLog": False,
            "error": None,
        }
        pool_payload: dict[str, Any] = {
            "statusStats": {},
            "accountStats": {},
            "quotaStats": {},
        }
        try:
            settings_payload = upstream_admin_request("GET", "/v2/settings")
            accounts_payload = upstream_admin_request("GET", "/v2/accounts", params={"page": 1, "pageSize": 20})
            upstream_payload = {
                "reachable": True,
                "edition": settings_payload.get("edition"),
                "version": settings_payload.get("version"),
                "currentAccountCount": int(settings_payload.get("currentAccountCount") or 0),
                "accountSelectionMode": settings_payload.get("accountSelectionMode"),
                "enableRequestLog": bool(settings_payload.get("enableRequestLog")),
                "error": None,
            }
            pool_payload = {
                "statusStats": accounts_payload.get("statusStats", {}),
                "accountStats": accounts_payload.get("accountStats", {}),
                "quotaStats": accounts_payload.get("quotaStats", {}),
            }
        except PortalError as exc:
            upstream_payload["error"] = exc.message

        return jsonify(
            {
                "portal": {
                    "userCount": int(totals["user_count"] or 0),
                    "enabledUserCount": int(totals["enabled_user_count"] or 0),
                    "adminCount": int(admin_count or 0),
                    "portalBaseUrl": portal_base_url(),
                    "apiBaseUrl": api_base_url(),
                    "providerCounts": provider_counts,
                },
                "upstream": upstream_payload,
                "pool": pool_payload,
            }
        )

    @app.get("/api/admin/settings")
    def admin_settings():
        require_admin()
        upstream_payload = {
            "reachable": False,
            "edition": None,
            "version": None,
            "currentAccountCount": 0,
            "accountSelectionMode": None,
            "enableRequestLog": False,
            "supportedAccountSelectionModes": [],
            "error": None,
        }
        try:
            payload = upstream_admin_request("GET", "/v2/settings")
            upstream_payload = {
                "reachable": True,
                "edition": payload.get("edition"),
                "version": payload.get("version"),
                "currentAccountCount": payload.get("currentAccountCount"),
                "accountSelectionMode": payload.get("accountSelectionMode"),
                "enableRequestLog": payload.get("enableRequestLog"),
                "supportedAccountSelectionModes": payload.get("supportedAccountSelectionModes", []),
                "error": None,
            }
        except PortalError as exc:
            upstream_payload["error"] = exc.message
        return jsonify(
            {
                "upstream": upstream_payload,
                "public": {
                    "portalBaseUrl": portal_base_url(),
                    "apiBaseUrl": api_base_url(),
                    "adminBaseUrl": admin_base_url(),
                },
                "entries": [serialize_entry_provider(row, include_health=True) for row in list_entry_provider_rows()],
            }
        )

    @app.get("/api/admin/providers")
    def admin_list_entry_providers():
        require_admin()
        return jsonify({"providers": [serialize_entry_provider(row, include_health=True) for row in list_entry_provider_rows()]})

    @app.get("/api/admin/providers/<entry_key>/diagnostics")
    def admin_entry_provider_diagnostics(entry_key: str):
        require_admin()
        row = find_entry_provider_row(entry_key)
        return jsonify({"diagnostics": build_entry_provider_diagnostics(row)})

    @app.put("/api/admin/providers/<entry_key>")
    def admin_update_entry_provider(entry_key: str):
        require_admin()
        payload = parse_json_body()
        row = find_entry_provider_row(entry_key)
        validated = validate_entry_provider_payload(row, payload)
        assert_provider_update_allowed(row, validated, payload)
        with open_db() as conn:
            conn.execute(
                """
                UPDATE portal_entry_providers
                SET label = ?, enabled = ?, description = ?, public_url = ?, admin_url = ?,
                    api_base_url = ?, health_url = ?, admin_api_key_encrypted = ?, default_allowed_groups = ?,
                    default_concurrency = ?, initial_balance = ?, embed_mode = ?, updated_at = ?
                WHERE entry_key = ?
                """,
                (
                    validated["label"],
                    1 if validated["enabled"] else 0,
                    validated["description"],
                    validated["public_url"],
                    validated["admin_url"],
                    validated["api_base_url"],
                    validated["health_url"],
                    validated["admin_api_key_encrypted"],
                    validated["default_allowed_groups"],
                    validated["default_concurrency"],
                    validated["initial_balance"],
                    validated["embed_mode"],
                    isoformat(),
                    entry_key,
                ),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM portal_entry_providers WHERE entry_key = ?",
                (entry_key,),
            ).fetchone()
        return jsonify({"provider": serialize_entry_provider(updated, include_health=True)})

    @app.get("/api/admin/users")
    def admin_list_users():
        require_admin()
        try:
            upstream_lookup = {item.get("id"): item for item in upstream_user_list()}
        except PortalError:
            upstream_lookup = {}
        with open_db() as conn:
            rows = conn.execute("SELECT * FROM portal_users ORDER BY created_at DESC").fetchall()
        return jsonify({"users": [serialize_portal_user(row, upstream=upstream_lookup.get(row["upstream_user_id"], {})) for row in rows]})

    @app.post("/api/admin/users")
    def admin_create_user():
        require_admin()
        row = create_local_user(parse_json_body(), actor="admin")
        return jsonify({"user": serialize_portal_user(row)}), 201

    @app.patch("/api/admin/users/<public_id>")
    def admin_update_user(public_id: str):
        require_admin()
        row = find_local_user_by_public_id(public_id)
        payload = parse_json_body()
        validated = validate_user_payload({**serialize_portal_user(row), **payload}, require_password=False)
        new_password = str(payload.get("password", ""))

        if validated["provider_key"] != str(row["provider_key"] or "kiro"):
            raise PortalError("暂不支持直接切换已有用户的入口类型，请新建目标套餐用户。", 400)

        with open_db() as conn:
            conflict = conn.execute(
                "SELECT 1 FROM portal_users WHERE (workspace = ? OR email = ?) AND public_id != ?",
                (validated["workspace"], validated["email"], public_id),
            ).fetchone()
            if conflict:
                raise PortalError("工作区或邮箱已被其他用户占用。", 409)

        if str(row["provider_key"] or "kiro") == "kiro":
            upstream_admin_request(
                "PATCH",
                f"/v2/users/{row['upstream_user_id']}",
                json_body={
                    "name": validated["workspace"],
                    "daily_quota": validated["daily_quota"],
                    "monthly_quota": validated["monthly_quota"],
                    "request_quota": validated["request_quota"],
                    "rate_limit_rpm": validated["rate_limit_rpm"],
                    "enabled": validated["enabled"],
                    "notes": validated["notes"] or validated["usecase"] or row["notes"],
                },
            )
        elif str(row["provider_key"] or "kiro") == "sub2api" and not str(row["upstream_user_id"]).startswith("sub2api:"):
            provider_row = find_entry_provider_row("sub2api")
            update_payload: dict[str, Any] = {
                "email": validated["email"],
                "username": validated["workspace"],
                "notes": validated["notes"] or validated["usecase"] or row["notes"],
                "status": "active" if validated["enabled"] else "disabled",
            }
            if new_password:
                update_payload["password"] = new_password
            default_concurrency = int(provider_row["default_concurrency"] or 0)
            default_groups = json.loads(provider_row["default_allowed_groups"] or "[]")
            if default_concurrency > 0:
                update_payload["concurrency"] = default_concurrency
            if default_groups:
                update_payload["allowed_groups"] = default_groups
            sub2api_admin_request(
                provider_row,
                "PUT",
                f"/api/v1/admin/users/{row['upstream_user_id']}",
                json_body=update_payload,
            )

        with open_db() as conn:
            conn.execute(
                """
                UPDATE portal_users
                SET workspace = ?, email = ?, plan_key = ?, provider_key = ?, usecase = ?, notes = ?, enabled = ?,
                    daily_quota = ?, monthly_quota = ?, request_quota = ?, rate_limit_rpm = ?,
                    password_hash = COALESCE(?, password_hash), updated_at = ?
                WHERE public_id = ?
                """,
                (
                    validated["workspace"],
                    validated["email"],
                    validated["plan_key"],
                    validated["provider_key"],
                    validated["usecase"],
                    validated["notes"],
                    1 if validated["enabled"] else 0,
                    validated["daily_quota"],
                    validated["monthly_quota"],
                    validated["request_quota"],
                    validated["rate_limit_rpm"],
                    password_hash(new_password) if new_password else None,
                    isoformat(),
                    public_id,
                ),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM portal_users WHERE public_id = ?", (public_id,)).fetchone()
        return jsonify({"user": serialize_portal_user(refreshed)})

    @app.delete("/api/admin/users/<public_id>")
    def admin_delete_user(public_id: str):
        require_admin()
        row = find_local_user_by_public_id(public_id)
        if str(row["provider_key"] or "kiro") == "kiro":
            upstream_admin_request("DELETE", f"/v2/users/{row['upstream_user_id']}")
        elif str(row["provider_key"] or "kiro") == "sub2api" and not str(row["upstream_user_id"]).startswith("sub2api:"):
            provider_row = find_entry_provider_row("sub2api")
            sub2api_admin_request(provider_row, "DELETE", f"/api/v1/admin/users/{row['upstream_user_id']}")
        with open_db() as conn:
            clear_subject_sessions(conn, "user", row["id"])
            conn.execute("DELETE FROM portal_users WHERE public_id = ?", (public_id,))
            conn.commit()
        return jsonify({"ok": True})

    @app.post("/api/admin/users/<public_id>/rotate-key")
    def admin_rotate_user_key(public_id: str):
        require_admin()
        row = find_local_user_by_public_id(public_id)
        if str(row["provider_key"] or "kiro") != "kiro":
            raise PortalError("当前套餐不使用 Kiro API Key，无需轮换。", 400)
        upstream = upstream_admin_request("POST", f"/v2/users/{row['upstream_user_id']}/regenerate-key")
        with open_db() as conn:
            conn.execute(
                "UPDATE portal_users SET upstream_api_key = ?, updated_at = ? WHERE public_id = ?",
                (upstream["api_key"], isoformat(), public_id),
            )
            conn.commit()
            refreshed = conn.execute("SELECT * FROM portal_users WHERE public_id = ?", (public_id,)).fetchone()
        return jsonify({"user": serialize_portal_user(refreshed)})

    @app.get("/api/admin/accounts")
    def admin_accounts():
        require_admin()
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("pageSize", "50"))
        payload = upstream_admin_request("GET", "/v2/accounts", params={"page": page, "pageSize": page_size, "status": request.args.get("status", "all")})
        return jsonify(payload)

    @app.get("/api/admin/snapshots")
    def admin_snapshots():
        require_admin()
        limit = int(request.args.get("limit", "30"))
        return jsonify({"snapshots": list_snapshots(limit=limit)})

    @app.post("/api/admin/snapshots")
    def admin_create_snapshot():
        admin = require_admin()
        payload = parse_json_body()
        label = str(payload.get("label", "")).strip() or None
        keep_latest = int(payload.get("keepLatest") or DEFAULT_KEEP_LATEST)
        snapshot = create_snapshot(label=label, keep_latest=keep_latest, created_by=f"admin:{admin['email']}")
        return jsonify({"snapshot": snapshot}), 201

    @app.get("/api/admin/snapshots/<snapshot_id>/download")
    def admin_download_snapshot(snapshot_id: str):
        require_admin()
        archive_path = resolve_snapshot(snapshot_id)
        return send_file(archive_path, as_attachment=True, download_name=archive_path.name)

    # Registration Manager Routes
    @app.get("/api/admin/registration/accounts")
    def admin_list_registration_accounts():
        require_admin()
        with open_db() as conn:
            rows = conn.execute("SELECT * FROM registration_accounts ORDER BY created_at DESC").fetchall()
        accounts = []
        for row in rows:
            account = dict(row)
            # Decrypt sensitive data for display
            try:
                account['microsoft_refresh_token'] = decrypt_data(account['microsoft_refresh_token'])
                account['microsoft_client_id'] = decrypt_data(account['microsoft_client_id'])
            except Exception:
                # If decryption fails, show placeholder
                account['microsoft_refresh_token'] = "****"
                account['microsoft_client_id'] = "****"
            accounts.append(account)
        return jsonify({"accounts": accounts})

    @app.post("/api/admin/registration/accounts")
    def admin_create_registration_account():
        require_admin()
        payload = parse_json_body()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        refresh_token = str(payload.get("microsoft_refresh_token", ""))
        client_id = str(payload.get("microsoft_client_id", ""))

        if not email or "@" not in email:
            raise PortalError("请输入有效的邮箱地址。")
        if len(password) < 8:
            raise PortalError("密码至少需要8位。")
        if not refresh_token:
            raise PortalError("Microsoft刷新令牌是必需的。")
        if not client_id:
            raise PortalError("Microsoft客户端ID是必需的。")

        now = isoformat()
        with open_db() as conn:
            # Check for existing account
            existing = conn.execute("SELECT 1 FROM registration_accounts WHERE email = ?", (email,)).fetchone()
            if existing:
                raise PortalError("该邮箱已被注册。", 409)

            conn.execute(
                """
                INSERT INTO registration_accounts (
                    email, password_hash, password_encrypted, microsoft_refresh_token, microsoft_client_id,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    email,
                    password_hash(password),
                    encrypt_data(password),
                    encrypt_data(refresh_token),
                    encrypt_data(client_id),
                    now,
                    now,
                ),
            )
            account_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            row = conn.execute("SELECT * FROM registration_accounts WHERE id = ?", (account_id,)).fetchone()

        return jsonify({"account": dict(row)}), 201

    @app.delete("/api/admin/registration/accounts/<int:account_id>")
    def admin_delete_registration_account(account_id: int):
        require_admin()
        with open_db() as conn:
            row = conn.execute("SELECT * FROM registration_accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise PortalError("账户不存在。", 404)

            conn.execute("DELETE FROM registration_accounts WHERE id = ?", (account_id,))
            conn.commit()

        return jsonify({"ok": True})

    @app.post("/api/admin/registration/auto-create")
    def admin_auto_create_registration_account():
        require_admin()

        from full_auto_email_registration import create_fully_automated_account

        async def create_account():
            result = await create_fully_automated_account()

            if result and result.get("status") == "complete":
                # Account fully created with OAuth2 credentials
                email = result["email"]
                password = result["password"]
                refresh_token = result["microsoft_refresh_token"]
                client_id = result["microsoft_client_id"]

                now = isoformat()
                with open_db() as conn:
                    # Check for existing account
                    existing = conn.execute("SELECT 1 FROM registration_accounts WHERE email = ?", (email,)).fetchone()
                    if existing:
                        return {"error": "该邮箱已被注册。", "email": email}

                    conn.execute(
                        """
                        INSERT INTO registration_accounts (
                            email, password_hash, password_encrypted, microsoft_refresh_token, microsoft_client_id,
                            status, created_at, updated_at, error_message
                        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                        """,
                        (
                            email,
                            password_hash(password),
                            encrypt_data(password),
                            refresh_token,
                            client_id,
                            now,
                            now,
                            f"账户完全自动创建 - 策略: {result.get('strategy', 'unknown')} - 账户池ID: {result.get('pool_account_id', 'N/A')}"
                        ),
                    )
                    account_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.commit()

                return {
                    "success": True,
                    "account_id": account_id,
                    "email": email,
                    "message": "账户完全自动创建成功",
                    "strategy": result.get("strategy", "unknown"),
                    "pool_account_id": result.get("pool_account_id")
                }
            else:
                return {"error": "自动创建账户失败 - 账户池为空，请手动添加账户", "details": result}

        try:
            # Run async function in sync context
            import asyncio
            result = asyncio.run(create_account())
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": f"自动创建过程中出错: {str(e)}"}), 500

    @app.get("/api/admin/registration/jobs")
    def admin_list_registration_jobs():
        require_admin()
        with open_db() as conn:
            rows = conn.execute("SELECT * FROM registration_jobs ORDER BY created_at DESC").fetchall()
        return jsonify({"jobs": [dict(row) for row in rows]})

    @app.post("/api/admin/registration/jobs")
    def admin_create_registration_job():
        require_admin()
        payload = parse_json_body()
        job_name = str(payload.get("job_name", "")).strip()
        concurrency = int(payload.get("concurrency", 1))
        account_ids = payload.get("account_ids", [])

        if not job_name:
            job_name = f"Registration Job {now_utc().strftime('%Y%m%d-%H%M%S')}"

        if concurrency < 1 or concurrency > 10:
            raise PortalError("并发数必须在1-10之间。")

        now = isoformat()
        with open_db() as conn:
            # Count total accounts
            if account_ids:
                total_accounts = len(account_ids)
                # Verify accounts exist
                placeholders = ','.join('?' * len(account_ids))
                existing = conn.execute(f"SELECT COUNT(*) FROM registration_accounts WHERE id IN ({placeholders})", account_ids).fetchone()[0]
                if existing != total_accounts:
                    raise PortalError("部分账户不存在。")
            else:
                total_accounts = conn.execute("SELECT COUNT(*) FROM registration_accounts WHERE status = 'pending'").fetchone()[0]

            if total_accounts == 0:
                raise PortalError("没有待注册的账户。")

            conn.execute(
                """
                INSERT INTO registration_jobs (
                    job_name, status, total_accounts, concurrency, created_at
                ) VALUES (?, 'running', ?, ?, ?)
                """,
                (job_name, total_accounts, concurrency, now),
            )
            job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

        # Start the registration job in a background thread because Flask requests do not run inside an event loop.
        start_registration_job(job_id, account_ids, concurrency)

        return jsonify({"job_id": job_id, "message": "Registration job started."}), 201

    @app.get("/api/admin/registration/logs")
    def admin_get_registration_logs():
        require_admin()
        account_id = request.args.get("account_id", type=int)
        job_id = request.args.get("job_id", type=int)
        limit = int(request.args.get("limit", 100))

        with open_db() as conn:
            query = "SELECT * FROM registration_logs WHERE 1=1"
            params = []

            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)

            if job_id:
                query += " AND job_id = ?"
                params.append(job_id)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

        return jsonify({"logs": [dict(row) for row in rows]})

    @app.patch("/api/admin/accounts/<path:account_id>")
    def admin_patch_account(account_id: str):
        require_admin()
        response = upstream_admin_request("PATCH", f"/v2/accounts/{account_id}", json_body=parse_json_body())
        return jsonify({"ok": True, "data": response})

    @app.post("/api/admin/accounts/<path:account_id>/refresh")
    def admin_refresh_account(account_id: str):
        require_admin()
        response = upstream_admin_request("POST", f"/v2/accounts/{account_id}/refresh")
        return jsonify({"ok": True, "data": response})

    @app.delete("/api/admin/accounts/<path:account_id>")
    def admin_delete_account(account_id: str):
        require_admin()
        response = upstream_admin_request("DELETE", f"/v2/accounts/{account_id}")
        return jsonify({"ok": True, "data": response})

    @app.post("/api/admin/accounts/refresh-all")
    def admin_refresh_all_accounts():
        require_admin()
        response = upstream_admin_request("POST", "/v2/accounts/refresh-all")
        return jsonify({"ok": True, "data": response})

    @app.post("/api/admin/accounts/refresh-quotas")
    def admin_refresh_all_quotas():
        require_admin()
        response = upstream_admin_request("POST", "/v2/accounts/refresh-quotas")
        return jsonify({"ok": True, "data": response})

    @app.post("/api/admin/oauth/start")
    def admin_oauth_start():
        require_admin()
        payload = parse_json_body()
        label = str(payload.get("label", "")).strip() or f"relay-{now_utc().strftime('%Y%m%d-%H%M%S')}"
        enabled = bool(payload.get("enabled", True))
        response = upstream_admin_request("POST", "/v2/auth/start", json_body={"label": label, "enabled": enabled})
        return jsonify(response)

    @app.get("/api/admin/oauth/status/<auth_id>")
    def admin_oauth_status(auth_id: str):
        require_admin()
        response = upstream_admin_request("GET", f"/v2/auth/status/{auth_id}")
        return jsonify(response)

    @app.post("/api/admin/oauth/claim/<auth_id>")
    def admin_oauth_claim(auth_id: str):
        require_admin()
        response = upstream_admin_request("POST", f"/v2/auth/claim/{auth_id}")
        return jsonify(response)

    return app


async def run_registration_job(job_id: int, account_ids: List[int], concurrency: int) -> None:
    """Run registration job asynchronously"""
    service = get_registration_service(BASE_DIR, SETTINGS.encryption_key)

    try:
        with open_db() as conn:
            job_row = conn.execute("SELECT * FROM registration_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job_row:
                return

            if account_ids:
                placeholders = ",".join("?" * len(account_ids))
                accounts = conn.execute(
                    f"SELECT * FROM registration_accounts WHERE id IN ({placeholders}) AND status = 'pending'",
                    account_ids,
                ).fetchall()
            else:
                accounts = conn.execute("SELECT * FROM registration_accounts WHERE status = 'pending'").fetchall()

            conn.execute("UPDATE registration_jobs SET started_at = ? WHERE id = ?", (isoformat(), job_id))
            conn.commit()

        if not accounts:
            with open_db() as conn:
                conn.execute(
                    "UPDATE registration_jobs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                    ("No pending accounts matched the job.", isoformat(), job_id),
                )
                conn.commit()
            return

        processed_account_ids = [int(account["id"]) for account in accounts]
        semaphore = asyncio.Semaphore(concurrency)

        async def process_account(account: sqlite3.Row) -> None:
            async with semaphore:
                try:
                    with open_db() as conn:
                        conn.execute(
                            "INSERT INTO registration_logs (account_id, job_id, level, message, step, created_at) VALUES (?, ?, 'info', ?, 'start', ?)",
                            (account["id"], job_id, f"Starting registration for {account['email']}", isoformat()),
                        )
                        conn.commit()

                    encrypted_password = account["password_encrypted"]
                    if not encrypted_password:
                        raise PortalError("账户缺少可解密密码，请重新录入该账号后重试。")

                    password = decrypt_data(encrypted_password)
                    account_data = {
                        "email": account["email"],
                        "password": password,
                        "microsoft_refresh_token": account["microsoft_refresh_token"],
                        "microsoft_client_id": account["microsoft_client_id"],
                    }

                    result = await service.register_account(account_data)
                    error_message = str(result.get("error") or "").strip() or "Unknown error"
                    current_time = isoformat()

                    with open_db() as conn:
                        if result["success"]:
                            conn.execute(
                                """
                                UPDATE registration_accounts
                                SET status = 'completed', aws_builder_id = ?, kiro_config_path = ?,
                                    last_registration_attempt = ?, error_message = NULL, updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    result.get("aws_builder_id", ""),
                                    result.get("config_path", ""),
                                    current_time,
                                    current_time,
                                    account["id"],
                                ),
                            )
                            conn.execute(
                                "INSERT INTO registration_logs (account_id, job_id, level, message, step, created_at) VALUES (?, ?, 'info', ?, 'complete', ?)",
                                (account["id"], job_id, f"Registration completed for {account['email']}", current_time),
                            )
                        else:
                            conn.execute(
                                """
                                UPDATE registration_accounts
                                SET status = 'failed', error_message = ?, registration_attempts = registration_attempts + 1,
                                    last_registration_attempt = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (error_message, current_time, current_time, account["id"]),
                            )
                            conn.execute(
                                "INSERT INTO registration_logs (account_id, job_id, level, message, step, created_at) VALUES (?, ?, 'error', ?, 'failed', ?)",
                                (account["id"], job_id, f"Registration failed for {account['email']}: {error_message}", current_time),
                            )
                        conn.commit()
                except Exception as error:
                    message = format_exception_message(error)
                    current_time = isoformat()
                    with open_db() as conn:
                        conn.execute(
                            """
                            UPDATE registration_accounts
                            SET status = 'failed', error_message = ?, registration_attempts = registration_attempts + 1,
                                last_registration_attempt = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (message, current_time, current_time, account["id"]),
                        )
                        conn.execute(
                            "INSERT INTO registration_logs (account_id, job_id, level, message, step, created_at) VALUES (?, ?, 'error', ?, 'error', ?)",
                            (account["id"], job_id, f"Registration error for {account['email']}: {message}", current_time),
                        )
                        conn.commit()

        await asyncio.gather(*(process_account(account) for account in accounts), return_exceptions=False)

        with open_db() as conn:
            placeholders = ",".join("?" * len(processed_account_ids))
            completed_count = conn.execute(
                f"SELECT COUNT(*) FROM registration_accounts WHERE id IN ({placeholders}) AND status = 'completed'",
                processed_account_ids,
            ).fetchone()[0]
            failed_count = conn.execute(
                f"SELECT COUNT(*) FROM registration_accounts WHERE id IN ({placeholders}) AND status = 'failed'",
                processed_account_ids,
            ).fetchone()[0]
            job_status = "completed" if failed_count == 0 else "failed"
            conn.execute(
                """
                UPDATE registration_jobs
                SET status = ?, completed_accounts = ?, failed_accounts = ?, completed_at = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    job_status,
                    completed_count,
                    failed_count,
                    isoformat(),
                    None if failed_count == 0 else f"{failed_count} account(s) failed during registration.",
                    job_id,
                ),
            )
            conn.commit()
    except Exception as error:
        with open_db() as conn:
            conn.execute(
                "UPDATE registration_jobs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?",
                (format_exception_message(error), isoformat(), job_id),
            )
            conn.commit()


def start_registration_job(job_id: int, account_ids: List[int], concurrency: int) -> None:
    def runner() -> None:
        asyncio.run(run_registration_job(job_id, account_ids, concurrency))

    thread = threading.Thread(target=runner, name=f"registration-job-{job_id}", daemon=True)
    thread.start()


def run_server(host: str, port: int) -> None:
    ensure_database()
    maybe_bootstrap_admin_from_env()
    application = create_app()
    print(f"Relay portal listening on http://{host}:{port}")
    serve(application, host=host, port=port, threads=12)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Relay portal service.")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the web service.")
    serve_parser.add_argument("--host", default=os.getenv("RELAY_BIND_HOST", "127.0.0.1"))
    serve_parser.add_argument("--port", type=int, default=int(os.getenv("RELAY_PORT", "4173")))

    admin_parser = subparsers.add_parser("bootstrap-admin", help="Create or reset a local portal admin.")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--password", required=True)
    admin_parser.add_argument("--name", default="Relay Admin")

    args = parser.parse_args()

    if args.command == "bootstrap-admin":
        ensure_database()
        action, _ = bootstrap_admin(args.email, args.password, args.name)
        print(f"Admin {action}: {args.email.strip().lower()}")
        return

    host = getattr(args, "host", os.getenv("RELAY_BIND_HOST", "127.0.0.1"))
    port = getattr(args, "port", int(os.getenv("RELAY_PORT", "4173")))
    run_server(host, port)


if __name__ == "__main__":
    main()
