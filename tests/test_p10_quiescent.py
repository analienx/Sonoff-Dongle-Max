"""Synthetic fail-closed Supervisor+Docker quiescence checks."""
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from p10_ha_state import addon_quiescent

class QuiescenceTests(TestCase):
    def client(self,status=0,raw=b'false\n'):
        c=MagicMock();out=MagicMock();out.read.return_value=raw
        out.channel.recv_exit_status.return_value=status
        c.exec_command.return_value=(None,out,None)
        return c

    def test_stopped_container_exited(self):
        self.assertTrue(addon_quiescent(self.client(),{'state':'stopped'})['addon_quiescent'])

    def test_error_after_disconnect_container_exited(self):
        self.assertTrue(addon_quiescent(self.client(),{'state':'error'})['crash_state_recovered_for_handoff'])

    def test_started_rejected_before_docker(self):
        c=self.client()
        with self.assertRaisesRegex(RuntimeError,'Supervisor state'):addon_quiescent(c,{'state':'started'})
        c.exec_command.assert_not_called()

    def test_running_container_rejected_even_if_supervisor_error(self):
        with self.assertRaisesRegex(RuntimeError,'container is running'):
            addon_quiescent(self.client(raw=b'true\n'),{'state':'error'})

    def test_unknown_container_state_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'Cannot verify'):
            addon_quiescent(self.client(status=1,raw=b''),{'state':'stopped'})
