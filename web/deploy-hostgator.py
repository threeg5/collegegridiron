"""Upload web/dist to HostGator over explicit FTPS (port 21).

Reads gitignored .env.hostgator.ftp next to this script. Does not print
the password. Refuses to connect if the password is missing or a placeholder.
"""

from __future__ import annotations

import ssl
import sys
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_DIR = WEB_DIR.parent
ENV_FILE = WEB_DIR / ".env.hostgator.ftp"
DIST_DIR = WEB_DIR / "dist"

REQUIRED_FILES = ("index.html", ".htaccess", "collegegridiron-mark.png")
REQUIRED_DIRS = ("assets",)
OPTIONAL_FILES = ("og-image.png",)
PLACEHOLDERS = {"", "placeholder", "your_password_here", "changeme", "todo"}

# Prefer the live HostGator folder. A chrooted account may already be
# sitting in public_html/collegegridiron (pwd=/), which is why "." is last.
REMOTE_DIR_FALLBACKS = (
    "public_html/collegegridiron",
    "collegegridiron",
    "public_html",
    ".",
    "/",
)


class ExplicitFTPTLS(FTP_TLS):
    """Explicit FTPS with TLS session reuse (needed by many HostGator servers)."""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn,
                server_hostname=self.host,
                session=self.sock.session,
            )
        return conn, size


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_get(file_vals: dict[str, str], key: str, default: str = "") -> str:
    import os

    return (os.environ.get(key) or file_vals.get(key) or default).strip()


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def check_dist() -> None:
    if not DIST_DIR.is_dir():
        fail(
            f"Missing {DIST_DIR}. Run `npm run build:hostgator` from web/ first."
        )
    missing = [name for name in REQUIRED_FILES if not (DIST_DIR / name).is_file()]
    missing += [name for name in REQUIRED_DIRS if not (DIST_DIR / name).is_dir()]
    if missing:
        fail(
            "web/dist is missing required files: "
            + ", ".join(missing)
            + ". Run `npm run build:hostgator` from web/."
        )


def connect(host: str, port: int, user: str, password: str) -> ExplicitFTPTLS:
    ctx = ssl.create_default_context()
    # Addon FTP hostnames often do not match HostGator's certificate CN.
    ctx.check_hostname = False
    ftp = ExplicitFTPTLS(context=ctx)
    ftp.connect(host, port, timeout=45)
    try:
        ftp.auth()
    except error_perm as exc:
        print(f"AUTH TLS note: {exc}")
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def list_names(ftp: ExplicitFTPTLS) -> list[str]:
    try:
        return ftp.nlst()
    except error_perm:
        return []


def cwd_parts(ftp: ExplicitFTPTLS, path: str) -> str:
    if path not in (".", "/", ""):
        ftp.cwd("/")
        for part in path.replace("\\", "/").split("/"):
            if not part or part == ".":
                continue
            ftp.cwd(part)
    return ftp.pwd()


def cwd_remote(ftp: ExplicitFTPTLS, preferred: str) -> str:
    start_names = list_names(ftp)
    print(f"FTP home listing: {', '.join(start_names) or '(empty)'}")

    candidates = [preferred, *REMOTE_DIR_FALLBACKS]
    seen: set[str] = set()
    last_error: Exception | None = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            ftp.cwd("/")
            pwd = cwd_parts(ftp, candidate)
            names = list_names(ftp)
            print(f"Tried {candidate} -> pwd={pwd} files={', '.join(names) or '(empty)'}")
            if candidate in (".", "/"):
                print("Skip site-root fallback; collegegridiron must be its own folder")
                continue
            if candidate == "public_html":
                inner = list_names(ftp)
                nameset = {n.split("/")[-1] for n in inner}
                if "collegegridiron" not in nameset:
                    try:
                        ftp.mkd("collegegridiron")
                        print("Created public_html/collegegridiron")
                    except error_perm as exc:
                        print(f"mkd collegegridiron: {exc}")
                        continue
                ftp.cwd("collegegridiron")
                pwd = ftp.pwd()
                names = list_names(ftp)
                print(f"Entered public_html/collegegridiron pwd={pwd} files={', '.join(names) or '(empty)'}")
                return "public_html/collegegridiron"
            return candidate
        except error_perm as exc:
            last_error = exc
            print(f"Cannot cwd {candidate}")
    fail(f"Could not cwd into a live-site folder. Last error: {last_error}")


def chmod_public(ftp: ExplicitFTPTLS, local_root: Path) -> None:
    try:
        ftp.sendcmd("SITE CHMOD 755 .")
    except error_perm as exc:
        print(f"chmod . skipped: {exc}")
    try:
        ftp.sendcmd("SITE CHMOD 755 assets")
    except error_perm:
        pass
    for path in sorted(local_root.rglob("*")):
        relative = path.relative_to(local_root).as_posix()
        mode = "755" if path.is_dir() else "644"
        try:
            ftp.sendcmd(f"SITE CHMOD {mode} {relative}")
            print(f"chmod {mode} {relative}")
        except error_perm as exc:
            print(f"chmod skipped {relative}: {exc}")


def print_listing(ftp: ExplicitFTPTLS, label: str) -> None:
    print(f"LIST {label}:")
    try:
        ftp.retrlines("LIST")
    except error_perm as exc:
        print(f"  (list failed: {exc})")


def remote_size(ftp: ExplicitFTPTLS, name: str) -> str:
    try:
        return str(ftp.size(name))
    except Exception:
        return "?"


def ensure_remote_dir(ftp: ExplicitFTPTLS, remote_dir: str) -> None:
    if remote_dir in ("", ".", "/"):
        return
    parts = [p for p in remote_dir.replace("\\", "/").split("/") if p and p != "."]
    for i in range(len(parts)):
        path = "/".join(parts[: i + 1])
        try:
            ftp.mkd(path)
        except error_perm:
            pass


def upload_file(ftp: ExplicitFTPTLS, local: Path, remote: str) -> None:
    parent = str(Path(remote).parent).replace("\\", "/")
    if parent not in (".", ""):
        ensure_remote_dir(ftp, parent)
    with local.open("rb") as handle:
        ftp.storbinary(f"STOR {remote}", handle)
    print(f"Uploaded {remote}")


def upload_tree(ftp: ExplicitFTPTLS, local_root: Path) -> int:
    count = 0
    for path in sorted(local_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(local_root).as_posix()
        upload_file(ftp, path, relative)
        count += 1
    return count


def main() -> None:
    if not ENV_FILE.is_file():
        fail(
            f"Missing {ENV_FILE.name}. Copy .env.hostgator.ftp.example "
            "to .env.hostgator.ftp and set HOSTGATOR_FTP_PASS."
        )

    vals = parse_env(ENV_FILE)
    host = env_get(vals, "HOSTGATOR_FTP_HOST")
    user = env_get(vals, "HOSTGATOR_FTP_USER")
    password = env_get(vals, "HOSTGATOR_FTP_PASS")
    port_raw = env_get(vals, "HOSTGATOR_FTP_PORT", "21")
    remote_dir = env_get(vals, "HOSTGATOR_FTP_REMOTE_DIR", ".")

    if not host or not user:
        fail("HOSTGATOR_FTP_HOST and HOSTGATOR_FTP_USER are required.")
    try:
        port = int(port_raw)
    except ValueError:
        fail("HOSTGATOR_FTP_PORT must be an integer (21 for explicit FTPS).")

    if password.lower() in PLACEHOLDERS:
        fail(
            "HOSTGATOR_FTP_PASS is empty or a placeholder. "
            "Put the FTP password in web/.env.hostgator.ftp "
            "(gitignored) and re-run. No upload attempted."
        )

    check_dist()
    optional_present = [
        name for name in OPTIONAL_FILES if (DIST_DIR / name).is_file()
    ]
    print(f"Uploading {DIST_DIR} -> {host}:{port} as {user}")
    print("TLS: explicit FTPS")
    if optional_present:
        print("Optional files: " + ", ".join(optional_present))

    ftp = connect(host, port, user, password)
    count = 0
    try:
        cwd_remote(ftp, remote_dir)
        print_listing(ftp, "before upload")
        count = upload_tree(ftp, DIST_DIR)
        chmod_public(ftp, DIST_DIR)
        print("Remote sizes after upload:")
        for name in ("index.html", ".htaccess", "collegegridiron-mark.png", "og-image.png"):
            print(f"  {name} size={remote_size(ftp, name)}")
        print_listing(ftp, "after upload")
        try:
            ftp.cwd("assets")
            print_listing(ftp, "assets")
            for name in sorted(p.name for p in (DIST_DIR / "assets").iterdir() if p.is_file()):
                print(f"  assets/{name} size={remote_size(ftp, name)}")
            ftp.cwd("..")
        except error_perm:
            print("  (could not list remote assets/)")
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    print(f"Done. Uploaded {count} file(s).")
    print("Live: https://theprofitengineer.com/collegegridiron/")


if __name__ == "__main__":
    main()
