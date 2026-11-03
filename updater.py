"""KREW verified updater. No external Python dependencies.

A trusted publisher controls UPDATE_MANIFEST_URL. Updates execute Python code;
never point the manifest at repositories you do not control.

Use `python updater.py check`, `python updater.py apply` (bot stopped),
`python updater.py rollback` (bot stopped). For running bots use launcher.py.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

BASE = Path(__file__).resolve().parent
STATE_DIR = ".krew_updates"
MAX_MANIFEST = 32 * 1024
MAX_ZIP = 48 * 1024 * 1024
MAX_EXTRACTED = 130 * 1024 * 1024
MAX_FILES = 400
MAX_SINGLE = 32 * 1024 * 1024
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_ROOT = {
    "VERSION", "main.py", "launcher.py", "updater.py", "upgrade.py", "backup.py",
    "release_check.py", "README.md", "CHANGELOG.md", "RELEASE_CHECKLIST.md",
    "AUTO_UPDATE_GUIDE.md", "release_notes.json", "START_WINDOWS.txt", "Dockerfile", "compose.yaml",
    ".dockerignore", ".gitignore", ".env.example",
}
ALLOWED_FOLDERS = {"krew", "tests"}
DENIED_PARTS = {"__pycache__", "data", "logs", "backups", ".git", ".github", STATE_DIR}


class UpdateError(Exception):
    pass


def parse_version(value: str) -> tuple[int, int, int, int, int]:
    m = VERSION_RE.fullmatch(str(value).strip())
    if not m:
        raise UpdateError(f"Некорректная версия: {value!r}")
    major, minor, patch, rc = m.groups()
    return int(major), int(minor), int(patch), 1 if rc is None else 0, int(rc or 0)


def current_version(base: Path = BASE) -> str:
    return (base / "VERSION").read_text(encoding="utf-8").strip()


def permitted_hosts() -> set[str]:
    # A publisher can explicitly allow an HTTPS domain for release archives.
    raw = os.getenv("UPDATE_ALLOWED_HOSTS", "raw.githubusercontent.com,github.com,release-assets.githubusercontent.com,objects.githubusercontent.com")
    hosts = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if not hosts:
        raise UpdateError("UPDATE_ALLOWED_HOSTS пуст")
    return hosts


def validate_https(url: str, hosts: set[str]) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise UpdateError("Неверный URL")
    parts = urlparse(url)
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or not parts.hostname or parts.hostname.lower() not in hosts):
        raise UpdateError("Разрешены только HTTPS-ссылки с доверенных доменов")
    return url


def fetch_bytes(url: str, limit: int, hosts: set[str], opener=urlopen) -> bytes:
    validate_https(url, hosts)
    req = Request(url, headers={"User-Agent": "KREW-Updater/1.0", "Accept": "application/octet-stream"})
    try:
        with opener(req, timeout=20) as response:
            # Reject redirects to untrusted hosts and oversize content.
            validate_https(response.geturl(), hosts)
            advertised = response.headers.get("Content-Length", "")
            if advertised.isdigit() and int(advertised) > limit:
                raise UpdateError("Файл обновления слишком большой")
            data = response.read(limit + 1)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"Не удалось получить обновление: {type(exc).__name__}") from exc
    if len(data) > limit:
        raise UpdateError("Превышен лимит размера обновления")
    return data


def read_manifest(raw: bytes, *, channel: str, version: str, hosts: set[str]) -> dict | None:
    if len(raw) > MAX_MANIFEST:
        raise UpdateError("Слишком большой манифест")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise UpdateError("Некорректный JSON манифеста") from exc
    if not isinstance(obj, dict) or obj.get("schema") != 1:
        raise UpdateError("Неизвестный формат манифеста")
    if obj.get("channel") != channel:
        raise UpdateError("Канал обновлений не совпадает с конфигурацией")
    target = obj.get("version")
    if not isinstance(target, str):
        raise UpdateError("В манифесте отсутствует версия")
    if parse_version(target) <= parse_version(version):
        return None
    if channel == "stable" and "-rc." in target:
        raise UpdateError("Предварительные релизы запрещены в stable")
    validate_https(obj.get("url"), hosts)
    if not isinstance(obj.get("sha256"), str) or not HEX_RE.fullmatch(obj["sha256"]):
        raise UpdateError("Не указан SHA-256 в манифесте")
    return obj


def check_update(base: Path = BASE, opener=urlopen) -> dict | None:
    url = os.getenv("UPDATE_MANIFEST_URL", "").strip()
    if not url:
        raise UpdateError("UPDATE_MANIFEST_URL не настроен")
    hosts = permitted_hosts()
    raw = fetch_bytes(url, MAX_MANIFEST, hosts, opener)
    return read_manifest(raw, channel=os.getenv("UPDATE_CHANNEL", "beta").strip(),
                         version=current_version(base), hosts=hosts)


def allowed_member(name: str, info: zipfile.ZipInfo) -> PurePosixPath:
    if (not name or name.endswith("/") or name.startswith("/") or "\\" in name or "\x00" in name
            or any(ord(ch) < 32 for ch in name)):
        raise UpdateError("Небезопасный путь в архиве")
    path = PurePosixPath(name)
    parts = path.parts
    if (not parts or any(p in ("..", ".", "") or ":" in p or p in DENIED_PARTS for p in parts)):
        raise UpdateError("Запрещённый путь в архиве")
    if len(parts) == 1:
        if parts[0] not in ALLOWED_ROOT:
            raise UpdateError(f"Запрещённый файл верхнего уровня: {name}")
    elif parts[0] not in ALLOWED_FOLDERS or name.endswith((".pyc", ".pyo")):
        raise UpdateError(f"Запрещённый путь: {name}")
    # Unix ZIP external attributes: only regular files or unspecified Windows files.
    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type not in (0, stat.S_IFREG):
        raise UpdateError("Недопустимый тип файла (ссылка/устройство)")
    if info.flag_bits & 1:
        raise UpdateError("Зашифрованные ZIP-файлы запрещены")
    return path


def extract_verified_zip(archive: bytes, stage: Path, expected_version: str) -> list[str]:
    stage.mkdir(parents=True, exist_ok=False)
    names: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            if len(files) > MAX_FILES:
                raise UpdateError("Слишком много файлов в архиве")
            for info in files:
                relative = allowed_member(info.filename, info)
                if info.filename in names:
                    raise UpdateError("Повторяющийся путь в архиве")
                if info.file_size > MAX_SINGLE:
                    raise UpdateError("Слишком большой файл в архиве")
                total += info.file_size
                if total > MAX_EXTRACTED:
                    raise UpdateError("Превышен допустимый размер распакованных файлов")
                target = stage.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest, length=1024*1024)
                names.append(info.filename)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise UpdateError(f"ZIP повреждён или недоступен: {type(exc).__name__}") from exc
    required = {"VERSION", "main.py", "launcher.py", "updater.py", "krew/core.py", "krew/db.py"}
    if not required.issubset(set(names)):
        raise UpdateError("Архив не содержит необходимых файлов приложения")
    actual_version = (stage / "VERSION").read_text(encoding="utf-8").strip()
    if actual_version != expected_version:
        raise UpdateError("Версия в ZIP отличается от манифеста")
    return names


def prepare_update(manifest: dict, base: Path = BASE, opener=urlopen) -> tuple[Path, list[str]]:
    hosts = permitted_hosts()
    version = manifest["version"]
    if parse_version(version) <= parse_version(current_version(base)):
        raise UpdateError("Эта версия уже установлена или устарела")
    archive = fetch_bytes(manifest["url"], MAX_ZIP, hosts, opener)
    digest = hashlib.sha256(archive).hexdigest()
    if not hmac.compare_digest(digest, manifest["sha256"]):
        raise UpdateError("Хеш ZIP не совпал с манифестом — обновление остановлено")
    state = base / STATE_DIR
    state.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="staging-", dir=state))
    # extract_verified_zip creates directory itself, so use a child of the temp directory.
    target = stage / "files"
    try:
        names = extract_verified_zip(archive, target, version)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target, names


def backup_database(base: Path, destination: Path) -> None:
    source = base / "data/krew.sqlite3"
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise UpdateError("SQLite backup не прошёл проверку")
    except sqlite3.Error as exc:
        raise UpdateError("Не удалось создать резервную копию БД") from exc


def _copy_atomic(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".krew-new")
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def install_prepared(stage: Path, names: list[str], base: Path = BASE) -> Path:
    if not names:
        raise UpdateError("Нет файлов для установки")
    version = (stage / "VERSION").read_text(encoding="utf-8").strip()
    parse_version(version)
    if parse_version(version) <= parse_version(current_version(base)):
        raise UpdateError("Обновление не новее установленной версии")
    # Confirm files again before changing the running app.
    for name in names:
        if not (stage / name).is_file():
            raise UpdateError(f"Отсутствует файл {name}")
        info = zipfile.ZipInfo(name)
        allowed_member(name, info)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    journal = base / STATE_DIR / "backups" / stamp
    original = journal / "files"
    original.mkdir(parents=True, exist_ok=False)
    changed = []
    old_version = current_version(base)
    # SQLite backup is taken while the supervised bot is stopped.
    try:
        backup_database(base, journal / "database_before_update.sqlite3")
        for name in names:
            dest = base / name
            existed = dest.is_file()
            if existed:
                _copy_atomic(dest, original / name)
            changed.append({"name": name, "existed": existed})
        # Journal is recorded before writing any new files, so interruptions are recoverable.
        metadata = {"from": old_version, "to": version, "changed": changed, "status": "prepared"}
        (journal / "journal.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        for name in names:
            _copy_atomic(stage / name, base / name)
        metadata["status"] = "installed"
        (journal / "journal.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return journal
    except Exception:
        if (journal / "journal.json").is_file():
            restore_journal(journal, base, force=True)
        raise


def restore_journal(journal: Path, base: Path = BASE, *, force: bool = False) -> None:
    info_path = journal / "journal.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError("Журнал отката отсутствует или повреждён") from exc
    if not force and info["status"] != "installed":
        raise UpdateError("Обновление уже откачено или не установлено")
    for item in info["changed"]:
        name = item["name"]
        allowed_member(name, zipfile.ZipInfo(name))
        dest = base / name
        if item["existed"]:
            src = journal / "files" / name
            if not src.is_file():
                raise UpdateError(f"Отсутствует резервная копия файла {name}")
            _copy_atomic(src, dest)
        else:
            dest.unlink(missing_ok=True)
    info["status"] = "rolled_back"
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    # DB intentionally NOT reverted automatically: newer user messages could be lost.
    # Its snapshot is kept for a deliberate manual recovery.


def latest_journal(base: Path = BASE) -> Path:
    backup_dir = base / STATE_DIR / "backups"
    for folder in sorted((p for p in backup_dir.iterdir() if p.is_dir()), reverse=True) if backup_dir.exists() else ():
        try:
            info = json.loads((folder / "journal.json").read_text(encoding="utf-8"))
            if info.get("status") == "installed":
                return folder
        except (OSError, ValueError):
            continue
    raise UpdateError("Нет установленного обновления для отката")


def apply_once(base: Path = BASE, opener=urlopen) -> Path | None:
    manifest = check_update(base, opener)
    if manifest is None:
        return None
    stage, names = prepare_update(manifest, base, opener)
    try:
        return install_prepared(stage, names, base)
    finally:
        shutil.rmtree(stage.parent, ignore_errors=True)


def main() -> int:
    from main import load_dotenv
    load_dotenv(BASE / ".env")
    parser = argparse.ArgumentParser(description="Обновление KREW с проверкой SHA-256 и резервной копией")
    parser.add_argument("action", choices=("check", "apply", "rollback", "version"))
    args = parser.parse_args()
    try:
        if args.action == "version":
            print("KREW", current_version())
        elif args.action == "check":
            result = check_update()
            print("Новая версия:", result["version"] if result else "обновлений нет")
        elif args.action == "apply":
            print("⚠️ Перед установкой останови python main.py или launcher.py")
            answer = input("Бот остановлен? Введите YES: ").strip()
            if answer != "YES":
                print("Отменено")
                return 1
            journal = apply_once()
            print("Установлено, резервная копия:", journal if journal else "обновлений нет")
        elif args.action == "rollback":
            print("⚠️ Перед откатом останови бота")
            if input("Бот остановлен? Введите YES: ").strip() != "YES":
                return 1
            journal = latest_journal()
            restore_journal(journal)
            print("Код восстановлен. База данных не откатывалась. Резервная копия:", journal)
    except (UpdateError, OSError) as exc:
        print("❌", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
