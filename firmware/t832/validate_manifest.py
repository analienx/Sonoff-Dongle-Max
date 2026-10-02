#!/usr/bin/env python3
"""Static schema/policy validation for the T832 control manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ALLOWED = {
    "REQUIRED_CORRECTNESS",
    "RESTORE_COMPAT",
    "CAPACITY",
    "LARGE_NETWORK_BASELINE",
    "BOARD",
    "BUILD_ID",
    "DIAGNOSTIC",
    "EXPERIMENTAL_FIX",
}
COMPILED_PROOFS = {
    "effective_macros",
    "compile_assert",
    "source_compile_assert",
    "linked_build",
    "linker_map_stack",
    "linker_map_nvs",
    "linker_memory_margin",
    "project_contract",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        fail("manifest schema_version must be 2")
    if data.get("variant") != "T832-KCTRL-R0":
        fail("unexpected manifest variant")

    mutations = data.get("mutations")
    if not isinstance(mutations, list) or not mutations:
        fail("manifest mutations must be a non-empty list")

    ids: set[str] = set()
    symbols: set[str] = set()
    compile_symbols: set[str] = set()
    for m in mutations:
        for key in ("id", "classification", "kind", "target", "rationale", "proof"):
            if key not in m:
                fail(f"mutation missing {key}: {m}")
        if m["id"] in ids:
            fail(f"duplicate mutation id: {m['id']}")
        ids.add(m["id"])
        if m["classification"] not in ALLOWED:
            fail(f"invalid classification for {m['id']}: {m['classification']}")
        if m["classification"] == "EXPERIMENTAL_FIX":
            fail(f"EXPERIMENTAL_FIX is forbidden in KCTRL: {m['id']}")
        if len(m["rationale"].strip()) < 25:
            fail(f"rationale too weak for {m['id']}")
        if not isinstance(m["proof"], list) or not m["proof"]:
            fail(f"proof contract missing for {m['id']}")
        if m["classification"] in {"CAPACITY", "LARGE_NETWORK_BASELINE"}:
            if not (set(m["proof"]) & COMPILED_PROOFS):
                fail(f"capacity/baseline mutation lacks compiled proof: {m['id']}")

        symbol = m.get("symbol")
        if symbol:
            symbols.add(symbol)
        if m["kind"] in {"compile_define", "compile_define_flag", "compile_define_replace"}:
            if not symbol:
                fail(f"compile mutation missing symbol: {m['id']}")
            if symbol in compile_symbols:
                fail(f"compile symbol configured twice: {symbol}")
            compile_symbols.add(symbol)
            if m["kind"] == "compile_define" and m.get("upstream") not in (None, "disabled"):
                src = m.get("upstream_source")
                if not isinstance(src, dict) or not src.get("path") or not src.get("needle"):
                    fail(f"compile mutation lacks pinned upstream-default proof: {m['id']}")

    preserved = data["control_semantics"]["preserve_ti_release_defaults"]
    if len(preserved) != len(set(preserved)):
        fail("preserved TI semantic symbols contain duplicates")
    conflict = sorted(set(preserved) & compile_symbols)
    if conflict:
        fail(f"KCTRL mutation list overrides preserved TI release semantics: {conflict}")

    seed = data.get("project_seed_contract")
    if not isinstance(seed, dict):
        fail("project_seed_contract is required")
    inherited = seed.get("inherited_compile_settings", [])
    inactive = seed.get("inactive_feature_macros", [])
    inherited_symbols = [x.get("symbol") for x in inherited]
    if len(inherited_symbols) != len(set(inherited_symbols)):
        fail("duplicate inherited project-seed symbol")
    required_seed = {"MAX_DEVICE_TABLE_ENTRIES", "HEAPMGR_SIZE", "NVOCMP_NVPAGES"}
    if set(inherited_symbols) != required_seed:
        fail(
            f"project-seed inherited settings mismatch: "
            f"{sorted(set(inherited_symbols))} != {sorted(required_seed)}"
        )
    for setting in inherited:
        if setting.get("classification") != "INHERITED_SEED":
            fail(f"invalid project-seed classification: {setting}")
        if len(setting.get("rationale", "").strip()) < 25:
            fail(f"project-seed rationale too weak: {setting.get('symbol')}")
        if not setting.get("proof"):
            fail(f"project-seed proof missing: {setting.get('symbol')}")
    inactive_symbols = {x.get("symbol") for x in inactive}
    required_inactive = {
        "FEATURE_MAC_SECURITY",
        "FEATURE_FREQ_HOP_MODE",
        "ZSTACK_5_30_NV_MIGRATION",
        "ZSTACK_NVOCMP_MIGRATION",
    }
    if inactive_symbols != required_inactive:
        fail(f"inactive project-seed features mismatch: {sorted(inactive_symbols)}")

    board = data.get("board_contract")
    if not isinstance(board, dict):
        fail("board_contract is required")
    if board.get("uart") != {"rx_dio": 12, "tx_dio": 13}:
        fail("MR4U UART board contract must remain RX DIO12 / TX DIO13")
    if board.get("rf_switch") != {"rf_24ghz_dio": 28, "high_pa_dio": 29}:
        fail("MR4U RF switch board contract must remain DIO28/DIO29")
    if board.get("bootloader_backdoor") != {"dio": 15, "level": "active-low"}:
        fail("MR4U BSL/bootloader board contract must remain DIO15 active-low")
    if board.get("internal_nvs", {}).get("region_bytes") != 10240:
        fail("MR4U/T832 internal NVS board contract must be five 2 KiB pages")

    cp = data.get("capacity_policy")
    if not isinstance(cp, dict) or cp.get("status") != "PROVISIONAL_UNTIL_PRIVATE_GATE":
        fail("capacity policy must remain explicitly provisional until private gate")
    if by_id := {m["id"]: m for m in mutations}:
        if str(by_id["capacity.tc_devices"]["configured"]) != "128":
            fail("T832 R0 provisional TCLK control value must be 128")
        if str(by_id["capacity.neighbors"]["configured"]) != "80":
            fail("T832 R0 provisional neighbor control value must be 80")

    mc = data["memory_contract"]
    if mc["nvs_pages"] * mc["nvs_page_bytes"] != mc["expected_flash_nv_bytes"]:
        fail("NVS memory contract arithmetic mismatch")
    if mc["c_isr_stack_bytes"] != 4096:
        fail("T832 stack contract must remain 4096 bytes")
    if mc["minimum_linker_free_sram_bytes"] <= 0:
        fail("SRAM margin gate must be positive")

    required_ids = {
        "correctness.uart_tx_finished",
        "correctness.nvocmp_recover",
        "restore.nvexid",
        "restore.mt_sys_key_management",
        "restore.project_seed_nvs_pages",
        "headroom.c_isr_stack",
        "build.mt_version_identity",
        "board.remove_launchpad_buttons",
        "board.remove_launchpad_leds",
        "board.remove_launchpad_external_nvs",
    }
    missing = sorted(required_ids - ids)
    if missing:
        fail(f"required control mutations missing: {missing}")

    print(
        json.dumps(
            {
                "result": "PASS",
                "variant": data["variant"],
                "mutation_count": len(mutations),
                "compile_define_count": len(compile_symbols),
                "preserved_ti_semantic_count": len(preserved),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
