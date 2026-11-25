"""Gate, stage and verify the standalone VCDIFF release ZIP."""
import json
import subprocess
import sys
import zipfile

from build_kit import KIT, PROJECT, RELEASE, WORKSPACE, sha


def main():
    metadata = json.loads((RELEASE / "release.json").read_text("utf-8"))
    evidence = [PROJECT / "Analysis" / name for name in
                ("publication-authorization.json", "installer-validation.json")]
    verify = json.loads(evidence[1].read_text("utf-8"))
    local = json.loads((PROJECT / "patch/local-install.json").read_text("utf-8"))
    kit = {p.relative_to(KIT).as_posix(): p for p in sorted(KIT.rglob("*")) if p.is_file()}
    outputs = {x["file"]: x["sha256"] for x in local["files"]}
    hashes = {name: sha(path) for name, path in kit.items()}
    if verify["status"] != "passed" or verify["kit_files"] != hashes or verify["installed_outputs"] != outputs:
        raise ValueError("The exact kit must pass the installation replay first")

    tool_dir = WORKSPACE / "Tools/localization"
    sys.path.insert(0, str(tool_dir))
    from translation_workflow import Workflow

    def checked(path, game_path=None):
        record = {"path": path.relative_to(PROJECT).as_posix(), "sha256": sha(path)}
        if game_path:
            record["game_path"] = game_path
        return record

    export = json.loads((PROJECT / "TranslateFiles/reports/final_validation.json").read_text("utf-8"))
    statement = json.loads(evidence[0].read_text("utf-8"))["user_statement"]
    flow = Workflow(PROJECT)
    flow.record_release_acceptance({
        "authorization": "explicit_user_release",
        "in_game_validation": "pending",
        "accept_pending_runtime": True,
        "user_statement": statement,
        "game_version": metadata["game_version"],
        "platform": metadata["platform"],
        "translation_sha256": export["translation_sha256"],
        "payload_files": [checked(p, name) for name, p in kit.items()],
        "evidence_files": [checked(p) for p in evidence]
                          + [checked(PROJECT / local["patch"] / name) for name in outputs],
    })
    flow.release_check()
    command = [sys.executable, str(WORKSPACE / ".agents/skills/game-release-patch/scripts/create_release_patch.py"),
               "--project", str(PROJECT)]
    for key, value in metadata.items():
        if key != "launch_mode":
            command += ["--" + key.replace("_", "-"), value]
    for name, path in kit.items():
        command += ["--include", f"{path}={name}"]
    subprocess.run(command + ["--dry-run"], check=True)
    subprocess.run(command, check=True)

    dispatch = PROJECT / "Dispatch"
    files = dispatch / "Files"
    archive = dispatch / f'{metadata["game_name"]}_子非鱼汉化{metadata["version"]}.zip'
    with zipfile.ZipFile(archive) as initial:
        for name in ("补丁说明.txt", "SHA256SUMS.txt"):
            data = initial.read(name)
            if name == "补丁说明.txt":
                text = data.decode("utf-8-sig")
                text = text.replace("- v1.0（2026-11-26）：首次发布。", "v1.0：首次发布")
                data = text.encode("utf-8-sig")
            (files / name).write_bytes(data)
        manifest = json.loads(initial.read("PATCH_MANIFEST.json"))
    manifest["install_mode"] = "delta_script"
    manifest["launch_mode"] = metadata["launch_mode"]
    manifest["installed_outputs"] = [
        {"path": x["file"], "sha256": x["sha256"], "original_sha256": x["original_sha256"],
         "delta": "汉化文件/" + x["file"] + ".vcdiff"}
        for x in local["files"]
    ]
    (files / "PATCH_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    allowed = list(kit) + ["补丁说明.txt", "SHA256SUMS.txt", "PATCH_MANIFEST.json"]
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as final:
        for name in allowed:
            final.write(files / name, name)
    with zipfile.ZipFile(temporary) as final:
        assert final.testzip() is None and set(final.namelist()) == set(allowed)
        for name, expected in hashes.items():
            assert sha(files / name) == expected
            assert final.read(name) == (files / name).read_bytes()
    temporary.replace(archive)
    print("Release", archive.name, archive.stat().st_size, sha(archive))


if __name__ == "__main__":
    main()
