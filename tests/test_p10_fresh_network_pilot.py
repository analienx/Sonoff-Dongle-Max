from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_fresh_network_pilot as pilot


class FreshPilotTests(TestCase):
    def source(self):
        return {
            "version": 5,
            "homeassistant": {"enabled": True},
            "mqtt": {"server": "mqtt://broker:1883"},
            "serial": {
                "port": "/dev/serial/by-id/usb-SMLIGHT_test-if02",
                "adapter": "zstack",
                "baudrate": 115200,
                "rtscts": False,
            },
            "advanced": {
                "channel": 11,
                "network_key": [1] * 16,
                "pan_id": 1234,
                "ext_pan_id": [2] * 8,
                "transmit_power": 11,
            },
            "devices": {"0x1": {"friendly_name": "old"}},
            "groups": {31: {"friendly_name": "old-group"}},
        }

    def test_pilot_config_uses_isolated_discovery_instead_of_false_disable(self):
        source = self.source()
        result = pilot._pilot_config(source)
        self.assertNotIn("devices", result)
        self.assertNotIn("groups", result)
        self.assertTrue(result["homeassistant"]["enabled"])
        self.assertEqual(
            result["homeassistant"]["discovery_topic"],
            pilot.PILOT_DISCOVERY_TOPIC,
        )
        self.assertEqual(result["mqtt"]["base_topic"], pilot.PILOT_BASE_TOPIC)
        self.assertEqual(result["advanced"]["network_key"], "GENERATE")
        self.assertEqual(result["advanced"]["pan_id"], "GENERATE")
        self.assertEqual(result["advanced"]["ext_pan_id"], "GENERATE")
        self.assertEqual(result["advanced"]["transmit_power"], 11)
        self.assertEqual(source["advanced"]["network_key"], [1] * 16)

    def test_non_zstack_and_unstable_serial_are_refused(self):
        source = self.source()
        source["serial"]["adapter"] = "ember"
        with self.assertRaisesRegex(ValueError, "P10/Z-Stack"):
            pilot._pilot_config(source)

        source = self.source()
        source["serial"]["port"] = "/dev/ttyACM1"
        with self.assertRaisesRegex(ValueError, "by-id"):
            pilot._pilot_config(source)

    def test_sanitation_evidence_requires_all_zero_tables(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "evidence.json"
            good = {
                "format": pilot.SANITATION_FORMAT,
                "znp_revision": pilot.EXPECTED_ZNP_REVISION,
                "created_at_utc": "2026-09-26T00:00:00+00:00",
                "network_formed": False,
                "address_manager_used": 0,
                "security_manager_used": 0,
                "aps_link_key_data_used": 0,
                "tclk_used": 0,
            }
            path.write_text(json.dumps(good), encoding="utf-8")
            self.assertEqual(
                pilot._validate_sanitation_evidence(path)["address_manager_used"],
                0,
            )
            good["address_manager_used"] = 1
            path.write_text(json.dumps(good), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "address_manager"):
                pilot._validate_sanitation_evidence(path)

    def test_table_count_parser_uses_latest_observation(self):
        text = """fetched adapter address manager table (capacity=457, used=8)
fetched adapter security manager table (capacity=0, used=0)
fetched adapter aps link key data table (capacity=0, used=0)
fetched adapter tclk table (capacity=0, used=0)
fetched adapter address manager table (capacity=457, used=10)
"""
        result = pilot._table_counts_from_log(text)
        self.assertEqual(result["address_manager"]["used"], 10)
        self.assertEqual(result["tclk"]["used"], 0)

    def test_status_never_calls_dirty_tables_clean(self):
        snapshot = {
            "configuration": {
                "mqtt": {"base_topic": pilot.PILOT_BASE_TOPIC},
                "homeassistant": {"discovery_topic": pilot.PILOT_DISCOVERY_TOPIC},
                "advanced": {"channel": 11},
            },
            "addon_state": "started",
            "ordinary_devices": 0,
            "backup": {"devices": [{"ieee_address": "0011223344556677"}]},
            "table_counts": {
                "address_manager": {"capacity": 457, "used": 10},
                "security_manager": {"capacity": 0, "used": 0},
                "aps_link_key_data": {"capacity": 0, "used": 0},
                "tclk": {"capacity": 0, "used": 0},
            },
        }
        result = pilot._safe_status(snapshot)
        self.assertFalse(result["adapter_device_security_tables_clean"])
        self.assertEqual(result["coordinator_backup_device_entries"], 1)

    def test_database_counter_excludes_coordinator_and_groups(self):
        raw = b"\n".join([
            json.dumps({"type": "Coordinator"}).encode(),
            json.dumps({"type": "Group"}).encode(),
            json.dumps({"type": "Router"}).encode(),
        ])
        self.assertEqual(pilot._database_ordinary_count(raw), 1)
