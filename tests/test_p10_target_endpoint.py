"""Localhost ZNP fixture tests the remote probe without contacting an actual radio."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import p10_target_endpoint as subject


def framed(cmd, payload):
    body = bytes([len(payload), 0x61, cmd]) + payload
    checksum = 0
    for x in body:
        checksum ^= x
    return b'\xfe' + body + bytes([checksum])


class TargetEndpointTests(unittest.TestCase):
    def test_remote_probe_code_compiles(self):
        compile(subject.REMOTE, 'safe_ha_znp_probe', 'exec')

    def test_ping_version_only_on_simulated_local_radio(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        observed = []
        def emulate():
            try:
                with listener:
                    client, _ = listener.accept()
                    with client:
                        client.settimeout(5)
                        for cmd, payload in ((1, (1625).to_bytes(2, 'little')),
                                             (2, bytes([2, 1, 2, 7, 1]) +
                                              (20260310).to_bytes(4, 'little') + b'\x00')):
                            request = b''
                            while len(request) < 5:
                                request += client.recv(5-len(request))
                            observed.append(request)
                            client.sendall(framed(cmd, payload))
            except OSError:
                observed.append(b'error')

        worker = threading.Thread(target=emulate, daemon=True)
        worker.start()
        try:
            proc = subprocess.run([sys.executable, '-c', subject.REMOTE,
                                   '127.0.0.1', str(port)], capture_output=True,
                                  text=True, timeout=8)
        finally:
            worker.join(timeout=5)
            listener.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['revision'], 20260310)
        self.assertEqual(observed, [b'\xfe\x00\x21\x01\x20',
                                    b'\xfe\x00\x21\x02\x23'])


if __name__ == '__main__':
    unittest.main()
