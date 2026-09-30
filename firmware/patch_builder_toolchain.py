#!/usr/bin/env python3
"""Backport the upstream slt-free toolchain bootstrap onto pinned Nerivec builder.

Firmware source/manifests remain from the pinned Nerivec builder. Only build-tool
discovery/bootstrap files are changed. Fail closed on any unexpected source drift.
"""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

UPSTREAM_TOOLING_COMMIT = "9e7021458664028de119bfa11a8776628c4134c5"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

def patch_dockerfile(text: str) -> str:
    replacements = [
        (
            "5d13e09e605e5dfb94abeb0773055647764bb30d746916f3fc3991a48282a6ba",
            "74e6c34f8099c3695ebe20980d18d7d8dbfbb9ff8a87c96e9b39e7e3ea413d3d",
            "slc arm64 sha",
        ),
        (
            "slc-cli/6.0.22/slc-cli.linux.gtk.aarch64.zip",
            "slc-cli/6.0.23/slc-cli.linux.gtk.aarch64.zip",
            "slc arm64 url",
        ),
        (
            "f05e078b369d7e7dbfa31bdd2ad8edf61f04a9291393deab4702137639ba7d19",
            "15d0269cb3083f0c621857e18ae4039a74603e8e0e655e037d84b9ae8a6e6821",
            "slc amd64 sha",
        ),
        (
            "slc-cli/6.0.22/slc-cli.linux.gtk.x86_64.zip",
            "slc-cli/6.0.23/slc-cli.linux.gtk.x86_64.zip",
            "slc amd64 url",
        ),
        (
            "99fd45e5064b00ace957b4d12c00bb3c3b33845b4e65793fde99d4960004e091",
            "0260da657f31891ff39e24b182bf13bd01980ec948a20d612b9582d12132fe2e",
            "commander arm64 sha",
        ),
        (
            "commander/1.24.1/Commander_linux_aarch64_1v24p1b1980.tar.bz",
            "commander/1.24.3/Commander_linux_aarch64_1v24p3b1989.tar.bz",
            "commander arm64 url",
        ),
        (
            "3ba24eeaeb560e9db306a4d070e2bbe40b456701b4b87c53643a93ab1101b2c4",
            "26cd4ddf94c08e10818fdfbc1548120870cc5bfd70561bfb750acad4cc52bd9e",
            "commander amd64 sha",
        ),
        (
            "commander/1.24.1/Commander_linux_x86_64_1v24p1b1980.tar.bz",
            "commander/1.24.3/Commander_linux_x86_64_1v24p3b1989.tar.bz",
            "commander amd64 url",
        ),
    ]
    for old, new, label in replacements:
        text = replace_once(text, old, new, label)
    return text

def patch_build_project(text: str) -> str:
    text = replace_once(
        text,
        '''def is_running_in_docker() -> bool:
    """Check if we're running inside the Docker build container."""
    return os.environ.get("SILABS_FIRMWARE_BUILD_CONTAINER") == "1"
''',
        '''def is_running_in_docker() -> bool:
    """Check if we're running inside the Docker build container."""
    return (
        os.environ.get("SILABS_FIRMWARE_BUILD_CONTAINER") == "1"
        or pathlib.Path("/opt/silabs").is_dir()
    )
''',
        "docker detection",
    )
    text = replace_once(
        text,
        '''    if is_running_in_docker():
        root = pathlib.Path("/root/.silabs/slt/installs/conan/p")
        return list(root.glob("gcc-*/p")) + list(root.glob("llvm-*/p"))
''',
        '''    if is_running_in_docker():
        return list(pathlib.Path("/opt/toolchains").glob("*"))
''',
        "toolchain discovery",
    )
    text = replace_once(
        text,
        '''    if is_running_in_docker():
        paths = list(pathlib.Path("/").glob("*_sdk_*"))
        paths += list(
            pathlib.Path("/root/.silabs/slt/installs/conan/p").glob("simpl*/p")
        )
        return paths
''',
        '''    if is_running_in_docker():
        return list(pathlib.Path("/opt/silabs/sdks").glob("*sdk*"))
''',
        "sdk discovery",
    )
    marker = '''def get_sdk_default_paths() -> list[pathlib.Path]:
'''
    apack = '''def get_apack_default_paths() -> list[pathlib.Path]:
    """Return folders containing SLC adapter packs."""
    if is_running_in_docker():
        return [p.parent for p in pathlib.Path("/opt/silabs").glob("*/apack.json")]
    return []


'''
    text = replace_once(text, marker, apack + marker, "apack helper insertion")
    toolchain_arg = '''    parser.add_argument(
        "--toolchain",
        action="append",
        dest="toolchains",
        type=ensure_folder,
        default=get_toolchain_default_paths(),
        required=len(get_toolchain_default_paths()) == 0,
        help="Path to a GCC toolchain",
    )
'''
    toolpath_arg = toolchain_arg + '''    parser.add_argument(
        "--tool-path",
        action="append",
        dest="tool_paths",
        type=ensure_folder,
        default=get_apack_default_paths(),
        help="Path to a folder containing an SLC adapter pack",
    )
'''
    text = replace_once(text, toolchain_arg, toolpath_arg, "tool-path CLI")
    text = replace_once(
        text,
        '''            "--sdk", sdk,
            "--output-type", "vscode",
        ],
''',
        '''            "--sdk", sdk,
            "--output-type", "vscode",
        ]
        + [f"--tool-path={p}" for p in args.tool_paths]
        + [f"--toolchain-locations={'llvm' if is_llvm else 'gcc'}:{toolchain}"],
''',
        "slc tool paths",
    )
    text = replace_once(
        text,
        '''            "NINJA_EXE_PATH": shutil.which("ninja"),
            "SOURCE_DATE_EPOCH": str(int(args.build_timestamp.timestamp())),
''',
        '''            "NINJA_EXE_PATH": shutil.which("ninja"),
            "POST_BUILD_EXE": shutil.which("commander"),
            "SOURCE_DATE_EPOCH": str(int(args.build_timestamp.timestamp())),
''',
        "post build commander",
    )
    if "--repo-owner" not in text or "--repo-hash" not in text:
        raise RuntimeError("Nerivec custom build provenance CLI was lost")
    return text

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("builder", type=Path)
    ap.add_argument("tooling", type=Path)
    args = ap.parse_args()
    builder, tooling = args.builder, args.tooling
    for rel in ("Dockerfile", "pyproject.toml", "uv.lock"):
        src = tooling / rel
        if not src.is_file():
            raise RuntimeError(f"missing upstream tooling file: {src}")
        shutil.copy2(src, builder / rel)
    docker = builder / "Dockerfile"
    docker.write_text(patch_dockerfile(docker.read_text(encoding="utf-8")), encoding="utf-8")
    bp = builder / "tools" / "build_project.py"
    bp.write_text(patch_build_project(bp.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"patched {builder} with slt-free tooling from {UPSTREAM_TOOLING_COMMIT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
