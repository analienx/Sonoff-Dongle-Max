"""Tests for the undeployed T832 capture barrier candidate.

Structure tests parse deploy/t832_capture_barrier.yaml and prove every
destructive step is gated by a response_variable plus a template condition,
with bounded waits and no continue_on_error or notifications.

Chain tests walk the same step order with the real incident CLI and mocked
services (supervisor API shim, RTS helper shim): each injected failure must
halt the chain with the latch preserved, and success must reach stabilizing
with the RTS helper invoked exactly once after stop confirmation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BARRIER = REPO / "deploy" / "t832_capture_barrier.yaml"
SHELL_COMMANDS = REPO / "deploy" / "t832_shell_commands.yaml"
SPEC = importlib.util.spec_from_file_location("t832_incident", HERE / "t832_incident.py")
assert SPEC and SPEC.loader
incident = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(incident)

VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(template: str, values: dict) -> str:
    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise AssertionError(f"unbound template variable {name!r}")
        return str(values[name])

    return VAR_RE.sub(sub, " ".join(template.split()))


def load_shell_commands() -> dict:
    return yaml.safe_load(SHELL_COMMANDS.read_text(encoding="utf-8"))


def flatten_actions(actions: list) -> list:
    flat: list = []
    for step in actions:
        if not isinstance(step, dict):
            continue
        flat.append(step)
        repeat = step.get("repeat")
        if isinstance(repeat, dict):
            seq = repeat.get("sequence")
            if isinstance(seq, list):
                flat.extend(flatten_actions(seq))
    return flat


class BarrierStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.automations = yaml.safe_load(BARRIER.read_text(encoding="utf-8"))
        self.barrier = next(a for a in self.automations if a["id"] == "zigbee2mqtt_t832_capture_barrier")
        self.close = next(a for a in self.automations if a["id"] == "zigbee2mqtt_t832_stability_close")

    def test_modes_and_no_notifications(self) -> None:
        text = BARRIER.read_text(encoding="utf-8")
        self.assertNotIn("continue_on_error", text)
        self.assertNotIn("notify.", text)
        for automation in self.automations:
            self.assertEqual(automation.get("mode"), "single")

    def test_production_triggers_reused(self) -> None:
        ids = {t.get("id") for t in self.barrier["triggers"]}
        self.assertEqual(ids, {"mesh_outage", "bridge_offline", "radio_timeout"})

    def test_destructive_steps_gated(self) -> None:
        steps = flatten_actions(self.barrier["actions"])
        destructive = [
            (i, s)
            for i, s in enumerate(steps)
            if s.get("service") in {"hassio.addon_stop", "hassio.addon_start"}
            or s.get("service") == "shell_command.mr4u_p10_rts_reset"
        ]
        self.assertEqual(len(destructive), 3)
        for index, step in destructive:
            prior = steps[:index]
            responses = [s["response_variable"] for s in prior if "response_variable" in s]
            self.assertTrue(responses, f"no response_variable before {step.get('service')}")
            gate_ok = False
            for cond in prior:
                template = cond.get("condition") == "template" and cond.get("value_template", "")
                if template and any(var in template for var in responses):
                    gate_ok = True
            self.assertTrue(gate_ok, f"no response condition before {step.get('service')}")

    def test_rts_is_existing_helper_only(self) -> None:
        text = BARRIER.read_text(encoding="utf-8")
        self.assertIn("shell_command.mr4u_p10_rts_reset", text)
        for banned in ("usbreset", "reboot", "echo ", "gpioset", "uhubctl"):
            self.assertNotIn(banned, text)

    def test_waits_bounded(self) -> None:
        for automation in self.automations:
            for step in flatten_actions(automation["actions"]):
                if "wait_for_trigger" in step:
                    self.assertIn("timeout", step)
                    self.assertFalse(step.get("continue_on_timeout", True))
                if "delay" in step:
                    delay = step["delay"]
                    total = delay.get("seconds", 0) + 60 * delay.get("minutes", 0)
                    self.assertLessEqual(total, 600)

    def test_close_automation_order(self) -> None:
        services = [s.get("service") for s in self.close["actions"] if isinstance(s, dict)]
        self.assertLess(services.index("shell_command.t832_status"), services.index("shell_command.t832_observe"))
        self.assertLess(services.index("shell_command.t832_observe"), services.index("shell_command.t832_close_if_stable"))


class BarrierChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "z2m.log"
        self.log.write_text("2026-10-03T09:00:00Z zh:zstack:znp boot\n", encoding="utf-8")
        self.marker_log = self.root / "markers.log"
        self.addon_states = self.root / "addon_states.txt"
        self.commands = load_shell_commands()
        self.env = dict(os.environ)
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        self.env["T832_INCIDENT_ROOT"] = str(self.state)
        self.write_curl_shim()
        self.write_rts_shim(0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_curl_shim(self, states: list[str] | None = None) -> None:
        self.addon_states.write_text("\n".join(states or ["stopped"]) + "\n", encoding="utf-8")
        shim = self.bin / "curl"
        shim.write_text(
            "#!/bin/bash\n"
            f'head -n 1 "{self.addon_states}"\n'
            f'tail -n +2 "{self.addon_states}" > "{self.addon_states}.next"\n'
            f'mv "{self.addon_states}.next" "{self.addon_states}"\n',
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    def write_rts_shim(self, returncode: int) -> None:
        shim = self.bin / "mr4u_p10_rts_reset"
        shim.write_text(
            "#!/bin/bash\n"
            f'echo "rts-invoked" >> "{self.marker_log}"\n'
            f"exit {returncode}\n",
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    def mark(self, name: str) -> None:
        with self.marker_log.open("a", encoding="utf-8") as fh:
            fh.write(name + "\n")

    def markers(self) -> list[str]:
        if not self.marker_log.exists():
            return []
        return self.marker_log.read_text(encoding="utf-8").split()

    def run_tool(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HERE / "t832_incident.py"), "--root", str(self.state), *argv],
            capture_output=True,
            text=True,
            env=self.env,
        )

    def run_shell_template(self, name: str, values: dict | None = None) -> subprocess.CompletedProcess:
        rendered = render(self.commands[name], values or {})
        rendered = rendered.replace("python3 ", sys.executable + " ", 1)
        rendered = rendered.replace(" | python3 ", " | " + sys.executable + " ")
        return subprocess.run(
            rendered,
            shell=True,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def latch_status(self) -> str:
        latch = json.loads((self.state / "state" / "incident-latch.json").read_text(encoding="utf-8"))
        return str(latch.get("status"))

    def addon_state(self) -> str:
        rendered = render(self.commands["t832_addon_state"], {})
        rendered = rendered.replace(" | python3 ", " | " + sys.executable + " ")
        proc = subprocess.run(rendered, shell=True, capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return str(json.loads(proc.stdout).get("state"))

    def test_success_chain_reaches_stabilizing(self) -> None:
        artifact = self.root / "fw.hex"
        artifact.write_text(":020000040000FA\n", encoding="utf-8")
        self.assertEqual(self.run_tool("bind-firmware", "--artifact", str(artifact)).returncode, 0)

        cap = self.run_shell_template("t832_capture", {"trigger": "mesh_outage"})
        self.assertEqual(cap.returncode, 0, cap.stderr)
        cap_doc = json.loads(cap.stdout)
        self.assertTrue(cap_doc["ok"])

        auth = self.run_shell_template("t832_authorize_reset")
        self.assertEqual(auth.returncode, 0, auth.stderr)
        auth_doc = json.loads(auth.stdout)
        self.assertEqual(auth_doc["status"], "reset_authorized")
        self.assertEqual(auth_doc["incident_id"], cap_doc["incident_id"])

        mark = self.run_shell_template("t832_mark_recovering")
        self.assertEqual(mark.returncode, 0, mark.stderr)

        self.write_curl_shim(["starting", "stopped"])
        self.mark("addon-stop")
        for _ in range(6):
            if self.addon_state() == "stopped":
                break
        self.assertEqual(self.addon_state(), "stopped")

        rts = subprocess.run(
            [str(self.bin / "mr4u_p10_rts_reset")], capture_output=True, env=self.env
        )
        self.assertEqual(rts.returncode, 0)
        self.mark("addon-start")

        rec = self.run_shell_template(
            "t832_recovery_result",
            {"success": "true", "normal_traffic": "true", "zdo_ok": "true"},
        )
        self.assertEqual(rec.returncode, 0, rec.stderr)
        self.assertEqual(json.loads(rec.stdout)["status"], "stabilizing")

        obs = self.run_shell_template(
            "t832_observe",
            {"bridge_up": "true", "normal_traffic": "true", "zdo_ok": "true"},
        )
        self.assertEqual(obs.returncode, 0, obs.stderr)
        self.assertEqual(json.loads(obs.stdout)["observations"], 1)

        order = self.markers()
        self.assertLess(order.index("addon-stop"), order.index("rts-invoked"))
        self.assertLess(order.index("rts-invoked"), order.index("addon-start"))

    def test_capture_refused_without_binding(self) -> None:
        cap = self.run_shell_template("t832_capture", {"trigger": "mesh_outage"})
        self.assertNotEqual(cap.returncode, 0)
        self.assertFalse((self.state / "state" / "incident-latch.json").exists())
        self.assertNotIn("rts-invoked", self.markers())

    def test_tampered_bundle_halts_chain(self) -> None:
        artifact = self.root / "fw.hex"
        artifact.write_text(":020000040000FA\n", encoding="utf-8")
        self.run_tool("bind-firmware", "--artifact", str(artifact))
        cap_doc = json.loads(self.run_shell_template("t832_capture", {"trigger": "mesh_outage"}).stdout)
        bundle = Path(cap_doc["bundle"])
        (bundle / "manifest.json").write_text('{"tampered": true}\n', encoding="utf-8")
        auth = self.run_shell_template("t832_authorize_reset")
        self.assertNotEqual(auth.returncode, 0)
        self.assertEqual(self.latch_status(), "captured")
        self.assertNotIn("rts-invoked", self.markers())

    def test_stop_never_confirms_halts_before_rts(self) -> None:
        artifact = self.root / "fw.hex"
        artifact.write_text(":020000040000FA\n", encoding="utf-8")
        self.run_tool("bind-firmware", "--artifact", str(artifact))
        self.run_shell_template("t832_capture", {"trigger": "mesh_outage"})
        self.run_shell_template("t832_authorize_reset")
        self.run_shell_template("t832_mark_recovering")
        self.write_curl_shim(["started"] * 8)
        confirmed = False
        for _ in range(6):
            if self.addon_state() == "stopped":
                confirmed = True
                break
        self.assertFalse(confirmed)
        self.assertEqual(self.latch_status(), "recovering")
        self.assertNotIn("rts-invoked", self.markers())

    def test_rts_failure_halts_before_start(self) -> None:
        artifact = self.root / "fw.hex"
        artifact.write_text(":020000040000FA\n", encoding="utf-8")
        self.run_tool("bind-firmware", "--artifact", str(artifact))
        self.run_shell_template("t832_capture", {"trigger": "mesh_outage"})
        self.run_shell_template("t832_authorize_reset")
        self.run_shell_template("t832_mark_recovering")
        self.write_curl_shim(["stopped"])
        self.assertEqual(self.addon_state(), "stopped")
        self.write_rts_shim(3)
        rts = subprocess.run([str(self.bin / "mr4u_p10_rts_reset")], capture_output=True, env=self.env)
        self.assertEqual(rts.returncode, 3)
        self.assertEqual(self.latch_status(), "recovering")
        self.assertNotIn("addon-start", self.markers())

    def test_zdo_failure_marks_failed(self) -> None:
        artifact = self.root / "fw.hex"
        artifact.write_text(":020000040000FA\n", encoding="utf-8")
        self.run_tool("bind-firmware", "--artifact", str(artifact))
        self.run_shell_template("t832_capture", {"trigger": "mesh_outage"})
        self.run_shell_template("t832_authorize_reset")
        self.run_shell_template("t832_mark_recovering")
        rec = self.run_shell_template(
            "t832_recovery_result",
            {"success": "true", "normal_traffic": "true", "zdo_ok": "false"},
        )
        self.assertEqual(rec.returncode, 0, rec.stderr)
        failed = json.loads(rec.stdout)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_reason"], "no-zdo-verification")


if __name__ == "__main__":
    unittest.main()
