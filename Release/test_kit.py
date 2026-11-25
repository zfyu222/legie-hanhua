"""Replay the packaged player entries using disposable Steam data."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_kit import KIT, PROJECT, sha


def exercise(kit):
    receipt = json.loads((PROJECT / "patch/local-install.json").read_text("utf-8"))
    source = PROJECT / receipt["original_backup"]
    originals = {row["file"]: row["original_sha256"] for row in receipt["files"]}
    patched = {row["file"]: row["sha256"] for row in receipt["files"]}

    with tempfile.TemporaryDirectory(prefix="release-test-", dir=PROJECT / "Analysis") as folder:
        game = Path(folder) / "LEGIE 中文 空格"
        shutil.copytree(kit, game)
        for name in originals:
            shutil.copy2(source / name, game / name)
        save = game / "save" / "sample.dat"
        save.parent.mkdir()
        save.write_bytes(b"preserve save data")
        settings = game / "legie.ini"
        settings.write_bytes(b"[video]\r\nscale=2\r\n")

        def run(action, success=True):
            entry = {"Install": "安装汉化.cmd", "Uninstall": "卸载汉化.cmd"}[action]
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", entry], cwd=game, input=b"\r\n",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            if (result.returncode == 0) != success:
                raise RuntimeError(result.stdout.decode("utf-8", errors="replace"))

        def verify(expected):
            assert {name: sha(game / name) for name in expected} == expected
            assert save.read_bytes() == b"preserve save data"
            assert settings.read_bytes() == b"[video]\r\nscale=2\r\n"

        run("Install")
        verify(patched)
        times = {name: (game / name).stat().st_mtime_ns for name in patched}
        run("Install")
        assert times == {name: (game / name).stat().st_mtime_ns for name in patched}
        (game / "legie.sud").unlink()
        run("Install")
        verify(patched)
        run("Uninstall")
        verify(originals)
        run("Uninstall")
        verify(originals)
        (game / "legie.sud").write_bytes(b"unexpected version")
        run("Install", success=False)
        assert sha(game / "legie.exe") == originals["legie.exe"]
        assert (game / "legie.sud").read_bytes() == b"unexpected version"
        shutil.copy2(source / "legie.sud", game / "legie.sud")
        delta = game / "汉化文件" / "legie.sud.vcdiff"
        delta.write_bytes(delta.read_bytes() + b"corrupted")
        run("Install", success=False)
        verify(originals)
    return {
        "status": "passed",
        "kit_files": {path.relative_to(kit).as_posix(): sha(path) for path in sorted(kit.rglob("*")) if path.is_file()},
        "installed_outputs": patched,
        "checks": ["unicode_spaced_path", "clean_install", "repeat_install_no_rewrite",
                   "repair_missing_asset", "restore_originals", "repeat_uninstall",
                   "unsupported_input_untouched", "corrupt_delta_untouched", "preserve_saves_and_settings"],
    }


if __name__ == "__main__":
    kit = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else KIT
    report = exercise(kit)
    (PROJECT / "Analysis/installer-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print("Installer replay passed:", ", ".join(report["checks"]))
