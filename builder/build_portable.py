#!/usr/bin/env python3
"""Package a signed upstream LocalSend Windows ZIP into our community portable layout.

This script never collects data from a user's existing LocalSend installation.
The official GitHub asset's SHA-256 must match its published digest. For the
initial v1.18.2 build, a second independently recorded digest is pinned.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from PIL import Image

PINNED = {
    ("1.18.2", "x64"): "737aab1829d901e1d798cddd1e5fdc06ba9dfcc9ea50cfe3805e047005d5e71a",
    ("1.18.2", "arm64"): "e441259257f24557e1b21f15783af106b70229e36e789a2525b6726841fb7bc1",
}
ARCH_ASSET = {"x64": "x86-64", "arm64": "arm-64"}
REPO = "localsend/localsend"


def validate_version(version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Enter a stable release version such as 1.18.2 (without v)")
    return version


def get_api_json(url: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LocalSendPortableBuilder/1.0"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def get_release_asset(version: str, arch: str) -> tuple[str, str]:
    validate_version(version)
    if arch not in ARCH_ASSET:
        raise ValueError("Unsupported architecture")
    release = get_api_json(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}")
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Refusing draft or pre-release")
    wanted = f"LocalSend-{version}-windows-{ARCH_ASSET[arch]}.zip"
    matching = [item for item in release.get("assets", []) if item.get("name") == wanted]
    if len(matching) != 1:
        raise ValueError(f"Official release does not have exactly one {wanted} asset")
    asset = matching[0]
    uri = asset.get("browser_download_url", "")
    expected_url = f"https://github.com/{REPO}/releases/download/v{version}/{wanted}"
    if uri != expected_url:
        raise ValueError("Unexpected asset download URL")
    published = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", published):
        raise ValueError("Release asset is missing its SHA-256 digest; refusing unverified download")
    published_digest = published.partition(":")[2].lower()
    pin = PINNED.get((version, arch))
    if pin and published_digest != pin:
        raise ValueError("Official release SHA-256 does not match our pinned checksum")
    return uri, published_digest


def download(url: str, dest: Path, max_bytes: int) -> None:
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    headers = {"User-Agent": "LocalSendPortableBuilder/1.0"}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as r, dest.open("wb") as out:
        length = 0
        while part := r.read(1024 * 1024):
            length += len(part)
            if length > max_bytes:
                raise ValueError("Download exceeds expected size limit")
            out.write(part)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_members(archive: zipfile.ZipFile):
    members = archive.infolist()
    total = sum(info.file_size for info in members)
    if total > 350 * 1024 * 1024 or len(members) > 5000:
        raise ValueError("Suspiciously large archive")
    for info in members:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.parts or ":" in path.parts[0]:
            raise ValueError("Unsafe ZIP member path")
        if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
            raise ValueError("Archive contains a symbolic link")
    return members


def unpack_official_zip(archive_path: Path, app_folder: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = safe_members(archive)
        candidates = [PurePosixPath(info.filename.replace("\\", "/"))
                      for info in members if info.filename.replace("\\", "/").endswith("localsend_app.exe")]
        if len(candidates) != 1:
            raise ValueError("Cannot uniquely find official localsend_app.exe")
        app_prefix = candidates[0].parent
        for info in members:
            original = PurePosixPath(info.filename.replace("\\", "/"))
            try:
                relative = original.relative_to(app_prefix)
            except ValueError:
                continue
            if str(relative) in (".", "settings.json") or info.is_dir():
                continue
            dest = app_folder.joinpath(*relative.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, dest.open("wb") as out:
                shutil.copyfileobj(source, out)
    essentials = ["localsend_app.exe", "flutter_windows.dll", "rust_lib_localsend_app.dll",
                  "data/flutter_assets/AssetManifest.bin"]
    for name in essentials:
        if not (app_folder / name).is_file():
            raise RuntimeError("Incomplete official Flutter build: " + name)
    if (app_folder / "settings.json").exists():
        raise RuntimeError("App must not include an active settings file")


def render_icon(ico: Path, info: Path) -> None:
    shutil.copy2(ico, info / "appicon.ico")
    with Image.open(ico) as image:
        if image.format != "ICO":
            raise ValueError("Official icon is not an ICO file")
        for n in (16, 32, 75, 128, 256):
            large = image.convert("RGBA")
            result = large.resize((n, n), Image.Resampling.LANCZOS)
            result.save(info / f"appicon_{n}.png")


def appinfo(version: str) -> str:
    a, b, c = validate_version(version).split(".")
    return f"""[Format]
Type=PortableApps.comFormat
Version=3.9

[Details]
Name=LocalSend Portable
AppID=LocalSendPortable-community
Publisher=LocalSend contributors & Community portable packaging
Homepage=https://github.com/localsend/localsend
Category=Internet
Description=Send files securely to nearby devices over your local network
Language=Multilingual

[License]
Shareable=true
OpenSource=true
Freeware=true
CommercialUse=true

[Version]
PackageVersion={a}.{b}.{c}.0
DisplayVersion={version}

[Control]
Icons=1
Start=LocalSendPortable.exe
"""


def compile_launcher(source: Path, icon: Path, destination: Path) -> None:
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    if not csc.is_file():
        raise RuntimeError("Windows .NET Framework 4 compiler not found: " + str(csc))
    command = [str(csc), "/nologo", "/target:winexe", "/optimize+",
               f"/win32icon:{icon}", f"/out:{destination}",
               "/reference:System.Windows.Forms.dll", "/reference:System.Web.Extensions.dll",
               str(source)]
    subprocess.run(command, check=True)
    if not destination.exists():
        raise RuntimeError("Launcher compilation produced no executable")


def build(version: str, arch: str, work: Path) -> Path:
    version = validate_version(version)
    url, digest = get_release_asset(version, arch)
    script_dir = Path(__file__).resolve().parent
    out = work / "dist"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="localsend-build-") as temp_dir:
        temp = Path(temp_dir)
        official_zip = temp / "upstream.zip"
        download(url, official_zip, 150 * 1024 * 1024)
        actual = sha256_file(official_zip)
        if actual != digest:
            raise ValueError(f"Official archive SHA-256 mismatch: expected {digest}; got {actual}")
        print("Official LocalSend ZIP checksum verified:", actual)
        icon = temp / "app_icon.ico"
        icon_url = ("https://raw.githubusercontent.com/localsend/localsend/" +
                    f"v{version}/app/windows/runner/resources/app_icon.ico")
        download(icon_url, icon, 2 * 1024 * 1024)
        stage = temp / "LocalSendPortable"
        app = stage / "App" / "LocalSend"
        info = stage / "App" / "AppInfo"
        settings = stage / "Data" / "Settings"
        (stage / "Data" / "Received Files").mkdir(parents=True)
        (stage / "Data" / "Temp").mkdir(parents=True)
        (stage / "Other" / "Source").mkdir(parents=True)
        app.mkdir(parents=True)
        info.mkdir(parents=True)
        settings.mkdir(parents=True)
        unpack_official_zip(official_zip, app)
        # Intentionally do not package a settings.json in App, or any actual user data.
        (settings / "README.txt").write_text("LocalSendPortable.exe creates settings.json here on first use. Preserve Data on upgrades.\n", encoding="utf-8")
        (stage / "Data" / "Received Files" / "README.txt").write_text("Choose this directory under LocalSend Settings > Receive as your download destination.\n", encoding="utf-8")
        render_icon(icon, info)
        (info / "appinfo.ini").write_text(appinfo(version), encoding="utf-8")
        license_url = f"https://raw.githubusercontent.com/localsend/localsend/v{version}/LICENSE"
        download(license_url, stage / "Other" / "Source" / "LICENSE.txt", 2 * 1024 * 1024)
        (stage / "Other" / "Source" / "build-info.txt").write_text(
            f"Upstream: https://github.com/localsend/localsend\nVersion: {version}\nArchitecture: {arch}\n"
            f"Verified official ZIP SHA256: {actual}\nThis is a community portable repackaging, not an official LocalSend release.\n",
            encoding="utf-8")
        compile_launcher(script_dir / "LocalSendPortable.cs", icon, stage / "LocalSendPortable.exe")
        zip_path = out / f"LocalSend-{version}-{arch}-True-Portable.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as result:
            for file in sorted(stage.rglob("*")):
                if file.is_file():
                    result.write(file, file.relative_to(stage.parent).as_posix())
        verify_archive(zip_path)
        return zip_path


def verify_archive(path: Path):
    prefix = "LocalSendPortable/"
    required = ["LocalSendPortable.exe", "App/LocalSend/localsend_app.exe",
                "App/LocalSend/flutter_windows.dll", "App/LocalSend/rust_lib_localsend_app.dll",
                "App/LocalSend/data/flutter_assets/AssetManifest.bin", "App/AppInfo/appinfo.ini",
                "App/AppInfo/appicon.ico", "App/AppInfo/appicon_16.png", "App/AppInfo/appicon_32.png",
                "App/AppInfo/appicon_75.png", "App/AppInfo/appicon_128.png", "App/AppInfo/appicon_256.png"]
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = [prefix + item for item in required if prefix + item not in names]
        if missing:
            raise AssertionError("Portable ZIP missing required files: " + ", ".join(missing))
        if prefix + "App/LocalSend/settings.json" in names:
            raise AssertionError("Live settings.json must not be shipped in App")
        if prefix + "Data/Settings/settings.json" in names:
            raise AssertionError("Never ship a saved settings.json in build artifacts")
    print("Verified complete portable ZIP:", path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.18.2")
    parser.add_argument("--architecture", choices=("x64", "arm64"), default="x64")
    parser.add_argument("--work", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        print(build(args.version, args.architecture, args.work))
    except Exception as ex:
        print("BUILD FAILED:", str(ex), file=sys.stderr)
        raise
