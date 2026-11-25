"""Create the LEGIE release kit from the exact tested local build."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
RELEASE = PROJECT / "Release"
KIT = PROJECT / "Analysis" / "release-kit-v1"
DECODER = WORKSPACE / "Tools/xdelta3/v3.2.2/xdelta3-3.2.2-windows-x86_64/xdelta3.exe"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    receipt = json.loads((PROJECT / "patch/local-install.json").read_text("utf-8"))
    tools = KIT / "PatchTools"
    deltas = KIT / "汉化文件"
    tools.mkdir(parents=True, exist_ok=False)
    deltas.mkdir()
    shutil.copy2(DECODER, tools / DECODER.name)
    shutil.copy2(RELEASE / "player_patch.ps1", tools / "patch.ps1")
    manifest = {"decoder_sha256": sha(DECODER), "files": []}
    for entry in receipt["files"]:
        name = entry["file"]
        original = PROJECT / receipt["original_backup"] / name
        patched = PROJECT / receipt["patch"] / name
        installed = PROJECT / "Game" / name
        if (sha(original), sha(patched), sha(installed)) != (
            entry["original_sha256"], entry["sha256"], entry["sha256"]
        ):
            raise ValueError(f"Release file differs from the local tested build: {name}")
        delta = deltas / f"{name}.vcdiff"
        subprocess.run([str(DECODER), "-e", "-9", "-A", "-s", str(original),
                        str(patched), name + ".vcdiff"], cwd=deltas, check=True)
        manifest["files"].append({
            "name": name, "original": sha(original), "patched": sha(patched),
            "delta_sha256": sha(delta), "legacy": [],
        })
    (tools / "delta.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8-sig")
    license_dir = tools / "Licenses"
    license_dir.mkdir()
    license_sources = WORKSPACE / "Projects/lakeview-cabin-collection/Release/Licenses"
    for name in ("xdelta-LICENSE.txt", "NotoSansSC-OFL.txt"):
        shutil.copy2(license_sources / name, license_dir / name)
    (license_dir / "NOTICE.txt").write_text(
        "xdelta 3.2.2 — https://github.com/jmacd/xdelta\n"
        "Noto Sans SC and Noto Serif SC glyphs — https://github.com/notofonts/noto-cjk\n",
        "utf-8",
    )
    for action, name in (("Install", "安装汉化"), ("Uninstall", "卸载汉化")):
        (KIT / f"{name}.cmd").write_text(
            '@echo off\nchcp 65001 >nul\n'
            'powershell.exe -NoProfile -ExecutionPolicy Bypass '
            f'-File "%~dp0PatchTools\\patch.ps1" -Action {action}\n'
            'set "result=%errorlevel%"\npause\nexit /b %result%\n',
            encoding="ascii", newline="\r\n",
        )
    print("Delta sizes:", [(item.name, item.stat().st_size) for item in sorted(deltas.iterdir())])


if __name__ == "__main__":
    build()
