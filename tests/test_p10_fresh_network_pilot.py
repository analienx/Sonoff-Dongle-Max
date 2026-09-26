from pathlib import Path
import sys
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import p10_fresh_network_pilot as pilot


class FreshPilotConfigTests(TestCase):
    def source(self):
        return {
            "version": 5,
            "homeassistant": {"enabled": True, "legacy_action_sensor": False},
            "mqtt": {"server": "mqtt://broker:1883", "base_topic": "zigbee2mqtt"},
            "serial": {
                "port": "/dev/serial/by-id/usb-SMLIGHT_test-if02",
                "adapter": "zstack", "baudrate": 115200, "rtscts": False,
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
            "external_converters": ["foo.js"],
        }

    def test_fresh_config_is_isolated_and_preserves_runtime_tuning(self):
        src = self.source()
        out = pilot.pilot_config(src)
        self.assertNotIn("devices", out)
        self.assertNotIn("groups", out)
        self.assertFalse(out["homeassistant"]["enabled"])
        self.assertEqual(out["mqtt"]["base_topic"], pilot.PILOT_BASE_TOPIC)
        self.assertEqual(out["advanced"]["network_key"], "GENERATE")
        self.assertEqual(out["advanced"]["pan_id"], "GENERATE")
        self.assertEqual(out["advanced"]["ext_pan_id"], "GENERATE")
        self.assertEqual(out["advanced"]["channel"], 11)
        self.assertEqual(out["advanced"]["transmit_power"], 11)
        self.assertEqual(out["external_converters"], ["foo.js"])
        self.assertTrue(src["homeassistant"]["enabled"])

    def test_non_zstack_refused(self):
        src = self.source()
        src["serial"]["adapter"] = "ember"
        with self.assertRaisesRegex(ValueError, "P10/Z-Stack"):
            pilot.pilot_config(src)

    def test_unstable_serial_refused(self):
        src = self.source()
        src["serial"]["port"] = "/dev/ttyACM1"
        with self.assertRaisesRegex(ValueError, "by-id"):
            pilot.pilot_config(src)

    def test_rollback_surface_is_narrow(self):
        self.assertEqual(
            pilot.RESTORE_FILES,
            ("configuration.yaml", "database.db", "database.db.backup",
             "coordinator_backup.json", "state.json"),
        )
        self.assertNotIn("stack_config.json", pilot.RESTORE_FILES)
