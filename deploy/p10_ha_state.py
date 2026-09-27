"""Fail-closed Home Assistant Zigbee2MQTT inactivity check for USB handoff.

Supervisor may report ``error`` after an unplug/crash even when the add-on's
container has exited. Both Supervisor state and Docker's actual container state
must confirm quiescence before a serial probe, config write or new start.
"""
from __future__ import annotations
from p10_data_bundle import addon_info, ADDON


def addon_quiescent(client, info: dict | None = None) -> dict:
    details = addon_info(client) if info is None else info
    state = details.get('state')
    if state not in ('stopped', 'error'):
        raise RuntimeError('Zigbee2MQTT Supervisor state is not stopped or error')
    name = 'app_' + ADDON
    command = "docker inspect --format '{{.State.Running}}' " + name
    _, output, _ = client.exec_command(command, timeout=15)
    raw = output.read().decode('utf-8', errors='replace').strip()
    status = output.channel.recv_exit_status()
    if status == 0 and raw in ('true', 'false'):
        if raw != 'false':
            raise RuntimeError('Zigbee2MQTT container is running; refusing serial access')
    else:
        # HA may remove a stopped add-on container entirely. Accept absence only
        # when an exact-name Docker lookup confirms no such container exists.
        check = "docker ps -aq --filter name=^/" + name + "$"
        _, listed, _ = client.exec_command(check, timeout=15)
        matches = listed.read().decode('utf-8', errors='replace').strip()
        if listed.channel.recv_exit_status() != 0 or matches:
            raise RuntimeError('Cannot verify actual Zigbee2MQTT container state; refusing handoff')
    return {'addon_quiescent': True, 'supervisor_state': state,
            'addon_container_running': False,
            'crash_state_recovered_for_handoff': state == 'error'}
