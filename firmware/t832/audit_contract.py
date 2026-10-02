#!/usr/bin/env python3
"""Fail-closed compatibility and compiled-evidence gates for T832-KCTRL-R0."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SDK_VAR = "${COM_TI_SIMPLELINK_CC13XX_CC26XX_SDK_INSTALL_DIR}/"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def git_show_text(root: Path, commit: str, relative: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{relative}"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def git_tree_manifest(root: Path, commit: str, relative: str) -> dict[str, str]:
    """Return path -> Git blob SHA from the pinned commit, never the patched worktree."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", commit, "--", relative],
        check=True,
        text=True,
        capture_output=True,
    )
    result: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        meta, path = line.split("\t", 1)
        _mode, obj_type, sha = meta.split()
        if obj_type == "blob":
            result[path] = sha
    if not result:
        raise SystemExit(f"compatibility path missing from pinned commit: {relative}")
    return result


def find_project(examples: Path) -> Path:
    return examples / (
        "examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/ticlang/"
        "znp_LP_EM_CC2674P10_tirtos7_ticlang.projectspec"
    )


def run_compat(args: argparse.Namespace) -> None:
    manifest = load_json(args.manifest)
    compat = manifest["compatibility_contract"]
    sources = manifest["sources"]

    expected = {
        "sdk832": sources["simplelink_lowpower_f2_sdk"]["commit"],
        "sdk833": sources["simplelink_lowpower_f2_sdk_compat_reference"]["commit"],
        "examples": sources["simplelink_zstack_examples"]["commit"],
    }
    actual = {
        "sdk832": git_head(args.sdk832),
        "sdk833": git_head(args.sdk833),
        "examples": git_head(args.examples),
    }
    if actual != expected:
        raise SystemExit(f"source pin mismatch: actual={actual} expected={expected}")

    critical: dict[str, Any] = {}
    for rel in compat["required_equal_sdk_paths"]:
        a = git_tree_manifest(args.sdk832, actual["sdk832"], rel)
        b = git_tree_manifest(args.sdk833, actual["sdk833"], rel)
        if a != b:
            only_a = sorted(set(a) - set(b))[:20]
            only_b = sorted(set(b) - set(a))[:20]
            changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])[:20]
            raise SystemExit(
                f"8.32/8.33 critical path differs: {rel}; "
                f"only832={only_a} only833={only_b} changed={changed}"
            )
        digest = hashlib.sha256(
            "\n".join(f"{k} {v}" for k, v in sorted(a.items())).encode()
        ).hexdigest()
        critical[rel] = {"files": len(a), "tree_sha256": digest}

    # Manifest upstream values are claims about the pinned pristine TI 8.32
    # tree, not comments. Prove every declared source/default needle before
    # considering the control manifest trustworthy.
    upstream_defaults: dict[str, Any] = {}
    for mutation in manifest["mutations"]:
        source = mutation.get("upstream_source")
        if not source:
            continue
        pristine = git_show_text(args.sdk832, actual["sdk832"], source["path"])
        count = pristine.count(source["needle"])
        if count != 1:
            raise SystemExit(
                f"upstream-default proof failed for {mutation['id']}: "
                f"{source['path']} needle count={count}"
            )
        upstream_defaults[mutation["id"]] = {
            "path": source["path"],
            "needle": source["needle"],
            "count": count,
            "declared_upstream": mutation.get("upstream"),
        }

    # Prove the MR4U-relevant mapping against the pinned TI 8.32 board data.
    board_meta = git_show_text(
        args.sdk832, actual["sdk832"],
        "source/ti/boards/.meta/LP_EM_CC2674P10.syscfg.json",
    )
    ccfg_meta = git_show_text(
        args.sdk832, actual["sdk832"],
        "source/ti/common/.meta/lprf_ccfg_settings.js",
    )
    board_needles = {
        "uart_rx_dio12": '"RXD" : "18", /* DIO12 */',
        "uart_tx_dio13": '"TXD" : "19"  /* DIO13 */',
        "rf_24ghz_dio28": '"24GHZ": {"type": "RF_24GHZ", "connection": 41 /* DIO28 */}',
        "rf_high_pa_dio29": '"HIGH_PA": {"type": "RF_HIGH_PA", "connection": 42 /* DIO29 */}',
    }
    for label, needle in board_needles.items():
        if needle not in board_meta:
            raise SystemExit(f"8.32 board metadata missing {label}: {needle}")
    for needle in (
        "LP_EM_CC2674P10_CCFG_SETTINGS",
        "xoscCapArrayDelta: 0xD5",
        "dioBootloaderBackdoor: 15",
        'levelBootloaderBackdoor: "Active low"',
    ):
        if needle not in ccfg_meta:
            raise SystemExit(f"8.32 CCFG metadata missing MR4U/P10 contract token: {needle}")

    project = find_project(args.examples)
    if not project.exists():
        raise SystemExit(f"project seed missing: {project}")
    syscfg = args.examples / "examples/rtos/LP_EM_CC2674P10/zstack/znp/tirtos7/znp.syscfg"
    if not syscfg.exists():
        raise SystemExit(f"project SysConfig seed missing: {syscfg}")
    syscfg_text = syscfg.read_text(encoding="utf-8")
    if "NVS1.internalFlash.regionSize = 0x2800;" not in syscfg_text:
        raise SystemExit("T832 SysConfig seed does not use the five-page 0x2800 internal NVS region")
    forbidden_launchpad = (
        "Button.addInstance", "LED.addInstance", "CONFIG_BTN_", "CONFIG_LED_",
        "CONFIG_NVSEXTERNAL", "CONFIG_SPI_0", "MX25R8035F", "NVS2.",
    )
    present = [token for token in forbidden_launchpad if token in syscfg_text]
    if present:
        raise SystemExit(f"unpruned LaunchPad-only SysConfig dependencies: {present}")
    for token in (
        'Display_UART.$hardware = system.deviceData.board.components.XDS110UART;',
        'RF.$hardware = system.deviceData.board.components.RF;',
    ):
        if token not in syscfg_text:
            raise SystemExit(f"required P10 UART/RF SysConfig contract missing: {token}")

    project_text = project.read_text(encoding="utf-8")
    xml = ET.fromstring(project_text)
    node = xml.find("project")
    if node is None:
        raise SystemExit("projectspec has no <project>")

    if node.attrib.get("device") != compat["project_seed_device"]:
        raise SystemExit(f"unexpected project device: {node.attrib.get('device')}")
    if node.attrib.get("cgtVersion") != compat["project_seed_cgt_version"]:
        raise SystemExit(f"unexpected cgtVersion: {node.attrib.get('cgtVersion')}")

    compiler = node.attrib.get("compilerBuildOptions", "")
    linker = node.attrib.get("linkerBuildOptions", "")
    required_tokens = {
        "compiler NV pages": (compiler, "-DNVOCMP_NVPAGES=5"),
        "linker NV pages": (linker, "--define=NVOCMP_NVPAGES=5"),
        "HEAPMGR size": (compiler, "-DHEAPMGR_SIZE=6144"),
        "P10 device flag": (compiler, "-DEM_CC2674P10_LP"),
    }
    for label, (haystack, token) in required_tokens.items():
        if token not in haystack:
            raise SystemExit(f"project contract missing {label}: {token}")
    if "--define=NVOCMP_NVPAGES=2" in linker:
        raise SystemExit("project seed still contains conflicting linker NVOCMP_NVPAGES=2")

    project_defines = {
        match.group(1): (match.group(2) if match.group(2) is not None else "1")
        for match in re.finditer(
            r"-D([A-Za-z_]\w*)(?:=([^\s]+))?",
            compiler,
        )
    }
    seed_contract = manifest["project_seed_contract"]
    inherited_proof: dict[str, Any] = {}
    for setting in seed_contract["inherited_compile_settings"]:
        symbol = setting["symbol"]
        expected_value = str(setting["value"])
        actual_value = project_defines.get(symbol)
        if actual_value != expected_value:
            raise SystemExit(
                f"project seed define mismatch {symbol}: "
                f"actual={actual_value!r} expected={expected_value!r}"
            )
        inherited_proof[symbol] = {
            "configured": setting["value"],
            "projectspec_value": actual_value,
            "t832_capacity_authority": setting["t832_capacity_authority"],
            "runtime_scope": setting["runtime_scope"],
        }

    inactive_features: dict[str, str] = {}
    for feature in seed_contract["inactive_feature_macros"]:
        symbol = feature["symbol"]
        if symbol in project_defines:
            raise SystemExit(
                f"inactive T832 seed feature unexpectedly enabled: {symbol}"
            )
        inactive_features[symbol] = "absent_from_projectspec_compile_defines"

    # Every path directly referenced from the 8.33 project seed must exist in
    # the pinned 8.32 SDK. This proves the seed does not silently depend on an
    # 8.33-only SDK file/directory.
    refs = sorted(set(re.findall(
        re.escape(SDK_VAR) + r'([^\s"<>]+)',
        project_text,
    )))
    missing = [rel for rel in refs if not (args.sdk832 / rel).exists()]
    if missing:
        raise SystemExit(f"8.33 project seed references paths absent from 8.32: {missing[:40]}")

    evidence = {
        "gate": "T832 project-seed compatibility",
        "source_commits": actual,
        "projectspec_sha256": sha256_path(project),
        "device": node.attrib.get("device"),
        "cgt_version": node.attrib.get("cgtVersion"),
        "critical_equal_paths": critical,
        "upstream_default_proof": upstream_defaults,
        "board_contract": {
            "uart_rx_dio": 12,
            "uart_tx_dio": 13,
            "rf_24ghz_dio": 28,
            "rf_high_pa_dio": 29,
            "bootloader_backdoor_dio": 15,
            "internal_nvs_region_bytes": 0x2800,
            "launchpad_only_dependencies_present": [],
        },
        "sdk_832_project_references_checked": len(refs),
        "sdk_832_project_references_missing": [],
        "compiler_contract": {
            "NVOCMP_NVPAGES": 5,
            "HEAPMGR_SIZE": 6144,
            "EM_CC2674P10_LP": True,
        },
        "project_seed_inherited_settings": inherited_proof,
        "inactive_feature_macros": inactive_features,
        "linker_contract": {"NVOCMP_NVPAGES": 5},
        "result": "PASS",
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


def parse_macros(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^#define\s+([A-Za-z_]\w*)\s*(.*)$", line.strip())
        if m:
            result[m.group(1)] = m.group(2).strip() or "1"
    return result


def raw_header_values(path: Path, symbols: set[str]) -> dict[str, list[str]]:
    result = {s: [] for s in symbols}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*#define\s+([A-Za-z_]\w*)\s+(.+?)\s*$", line)
        if m and m.group(1) in result:
            result[m.group(1)].append(m.group(2))
    return {k: v for k, v in result.items() if v}


def memory_rows(map_text: str) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    # TI map format: name origin length used unused [attributes...]
    pat = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+"
        r"([0-9A-Fa-f]{8,})\s+([0-9A-Fa-f]{8,})\s+"
        r"([0-9A-Fa-f]{8,})\s+([0-9A-Fa-f]{8,})(?:\s|$)"
    )
    for line in map_text.splitlines():
        m = pat.match(line)
        if m:
            rows[m.group(1)] = {
                "origin": int(m.group(2), 16),
                "length": int(m.group(3), 16),
                "used": int(m.group(4), 16),
                "unused": int(m.group(5), 16),
            }
    return rows


def run_build(args: argparse.Namespace) -> None:
    manifest = load_json(args.manifest)
    patch = load_json(args.patch_evidence)
    mutations = manifest["mutations"]
    expected_ids = {m["id"] for m in mutations}
    applied_ids = {m["id"] for m in patch["applied_mutations"]}
    if applied_ids != expected_ids:
        raise SystemExit(
            f"patch/manifest coverage mismatch missing={sorted(expected_ids-applied_ids)} "
            f"extra={sorted(applied_ids-expected_ids)}"
        )

    # Prove the imported project's exact znp_cnf.opts is the patched SDK file.
    imported_opts = list(args.workspace.rglob("Stack/Config/znp_cnf.opts"))
    if len(imported_opts) != 1:
        raise SystemExit(f"expected one imported znp_cnf.opts, found {imported_opts}")
    sdk_opts = args.sdk / "source/ti/zstack/apps/znp/znp_cnf.opts"
    if sha256_path(imported_opts[0]) != sha256_path(sdk_opts):
        raise SystemExit("imported znp_cnf.opts differs from patched SDK source")

    # Preserve TI release semantics: these symbols must not be overridden by
    # T832 opts. Their effective values remain generated/default TI values.
    opts_text = imported_opts[0].read_text(encoding="utf-8")
    overridden = [
        s for s in manifest["control_semantics"]["preserve_ti_release_defaults"]
        if re.search(rf"^-D{re.escape(s)}(?:=|$)", opts_text, flags=re.MULTILINE)
    ]
    if overridden:
        raise SystemExit(f"KCTRL illegally overrides TI release semantics: {overridden}")

    macros = parse_macros(args.effective_macros)
    macro_proof: dict[str, Any] = {}
    compile_kinds = {"compile_define", "compile_define_flag", "compile_define_replace"}
    for m in (x for x in mutations if x["kind"] in compile_kinds):
        symbol = m["symbol"]
        actual = macros.get(symbol)
        if actual is None:
            raise SystemExit(f"effective macro missing: {symbol}")
        if m["kind"] != "compile_define_flag":
            expected = str(m["configured"])
            # Preserve symbolic TRUE/FALSE exactly; numeric values compare after
            # stripping harmless outer parentheses/suffix whitespace.
            if actual.strip() != expected:
                try:
                    if int(actual, 0) != int(expected, 0):
                        raise ValueError
                except ValueError:
                    raise SystemExit(
                        f"effective macro mismatch {symbol}: actual={actual!r} expected={expected!r}"
                    )
        macro_proof[symbol] = {
            "configured": m["configured"],
            "effective_preprocessor_value": actual,
            "mutation_id": m["id"],
        }

    generated_values = raw_header_values(
        args.generated_header,
        {m["symbol"] for m in mutations if m.get("symbol")},
    )

    map_text = args.map_file.read_text(encoding="utf-8", errors="replace")
    rows = memory_rows(map_text)
    if "FLASH_NV" not in rows or "SRAM" not in rows:
        raise SystemExit(
            f"linker map memory table incomplete; found rows={sorted(rows)}"
        )
    mc = manifest["memory_contract"]
    if rows["FLASH_NV"]["length"] != mc["expected_flash_nv_bytes"]:
        raise SystemExit(
            f"FLASH_NV length {rows['FLASH_NV']['length']} != "
            f"{mc['expected_flash_nv_bytes']}"
        )
    if rows["SRAM"]["length"] != mc["sram_bytes"]:
        raise SystemExit(
            f"SRAM length {rows['SRAM']['length']} != {mc['sram_bytes']}"
        )
    if rows["SRAM"]["unused"] < mc["minimum_linker_free_sram_bytes"]:
        raise SystemExit(
            f"SRAM margin {rows['SRAM']['unused']} < "
            f"{mc['minimum_linker_free_sram_bytes']}"
        )

    stack_hex = f"{mc['c_isr_stack_bytes']:08x}"
    stack_lines = [
        line for line in map_text.splitlines()
        if ".stack" in line.lower() and stack_hex in line.lower()
    ]
    if not stack_lines:
        raise SystemExit(
            f"linker map does not prove .stack size 0x{mc['c_isr_stack_bytes']:x}"
        )

    forbidden_seed_symbols = {
        "FEATURE_MAC_SECURITY": ("macSecurityPibDefaults", "macSecurityPibTbl"),
        "FEATURE_FREQ_HOP_MODE": ("FHPIB_defaults", "FH_PibTbl"),
        "ZSTACK_5_30_NV_MIGRATION": ("zgMigrateTo530SDK",),
        "ZSTACK_NVOCMP_MIGRATION": ("zgNVOCMPMigration",),
    }
    inactive_link_proof: dict[str, Any] = {}
    for feature in manifest["project_seed_contract"]["inactive_feature_macros"]:
        symbol = feature["symbol"]
        linked = [name for name in forbidden_seed_symbols[symbol] if name in map_text]
        if linked:
            raise SystemExit(
                f"inactive project-seed feature {symbol} appears linked: {linked}"
            )
        inactive_link_proof[symbol] = {
            "forbidden_symbols_checked": list(forbidden_seed_symbols[symbol]),
            "linked_symbols_found": [],
        }

    driver_configs = list(args.workspace.rglob("ti_drivers_config.c"))
    if len(driver_configs) != 1:
        raise SystemExit(f"expected one generated ti_drivers_config.c, found {driver_configs}")
    driver_text = driver_configs[0].read_text(encoding="utf-8", errors="replace")
    forbidden_generated = (
        "CONFIG_BTN_LEFT", "CONFIG_BTN_RIGHT", "CONFIG_GPIO_BTN1", "CONFIG_GPIO_BTN2",
        "CONFIG_LED_RED", "CONFIG_LED_GREEN", "CONFIG_NVSEXTERNAL", "CONFIG_SPI_0",
    )
    leaked = [token for token in forbidden_generated if token in driver_text]
    if leaked:
        raise SystemExit(f"LaunchPad-only peripherals leaked into generated driver config: {leaked}")

    if not args.out_file.exists() or args.out_file.stat().st_size == 0:
        raise SystemExit("linked .out artifact missing")

    evidence = {
        "gate": "T832 compiled contract",
        "manifest_sha256": sha256_path(args.manifest),
        "patch_evidence_sha256": sha256_path(args.patch_evidence),
        "linked_out_sha256": sha256_path(args.out_file),
        "imported_znp_cnf_opts_sha256": sha256_path(imported_opts[0]),
        "effective_macro_proof": macro_proof,
        "generated_header": {
            "path": str(args.generated_header),
            "sha256": sha256_path(args.generated_header),
            "declared_values_for_tracked_symbols": generated_values,
            "note": "effective values are proven by TI-Clang preprocessing of this generated header together with the exact imported znp_cnf.opts",
        },
        "linker_map": {
            "path": str(args.map_file),
            "sha256": sha256_path(args.map_file),
            "memory_rows": rows,
            "flash_nv_expected_bytes": mc["expected_flash_nv_bytes"],
            "sram_unused_bytes": rows["SRAM"]["unused"],
            "minimum_sram_unused_bytes": mc["minimum_linker_free_sram_bytes"],
            "stack_proof_lines": stack_lines[:8],
        },
        "ti_release_semantics_overrides": [],
        "inactive_project_seed_feature_link_proof": inactive_link_proof,
        "mutation_count": len(mutations),
        "result": "PASS",
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compat")
    c.add_argument("--manifest", type=Path, required=True)
    c.add_argument("--sdk832", type=Path, required=True)
    c.add_argument("--sdk833", type=Path, required=True)
    c.add_argument("--examples", type=Path, required=True)
    c.add_argument("--evidence", type=Path, required=True)

    b = sub.add_parser("build")
    b.add_argument("--manifest", type=Path, required=True)
    b.add_argument("--patch-evidence", type=Path, required=True)
    b.add_argument("--sdk", type=Path, required=True)
    b.add_argument("--workspace", type=Path, required=True)
    b.add_argument("--effective-macros", type=Path, required=True)
    b.add_argument("--generated-header", type=Path, required=True)
    b.add_argument("--map-file", type=Path, required=True)
    b.add_argument("--out-file", type=Path, required=True)
    b.add_argument("--evidence", type=Path, required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    if args.command == "compat":
        run_compat(args)
    else:
        run_build(args)


if __name__ == "__main__":
    main()
