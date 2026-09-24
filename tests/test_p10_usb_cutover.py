"""Synthetic-only USB cutover tests. Never store real network keys or device IDs here."""
import json
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import p10_usb_cutover as subject

OLD=(b'channel: 11\nserial:\n  port: /dev/serial/by-id/usb-SONOFF-example-if00\n'
     b'  adapter: ember\n  baudrate: 115200\n  rtscts: false\nmqtt:\n  server: mqtt://localhost\n')
TARGET='/dev/serial/by-id/usb-SMLIGHT-example-if01'

class UsbRendering(TestCase):
    def test_changes_only_port_and_adapter(self):
        result=subject.usb_yaml(OLD,TARGET)
        self.assertIn(('  port: '+TARGET).encode(),result)
        self.assertIn(b'  adapter: zstack',result)
        old_lines=OLD.splitlines(); new_lines=result.splitlines()
        self.assertEqual(len(old_lines),len(new_lines))
        self.assertEqual([i for i,(x,y) in enumerate(zip(old_lines,new_lines)) if x!=y],[2,3])
        self.assertIn(b'channel: 11',result)
        self.assertIn(b'mqtt://localhost',result)

    def test_refuses_unstable_or_windows_port(self):
        for candidate in ('COM4','/dev/ttyACM0','tcp://192.168.1.2:7638',
                          '/dev/serial/by-id/usb-radio\nserial: fake'):
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):
                subject.usb_yaml(OLD,candidate)

    def test_remote_probe_has_no_mutating_znp_commands(self):
        compile(subject.REMOTE,'<HA read-only USB probe>','exec')
        self.assertIn('command(1)',subject.REMOTE)
        self.assertIn('command(2)',subject.REMOTE)
        for forbidden in ('command(3)','SYS_RESET','NV_WRITE','formNetwork','factoryReset'):
            self.assertNotIn(forbidden,subject.REMOTE)

    def test_source_requires_verified_cold_bundle(self):
        with patch.object(subject,'private_target',side_effect=lambda value:value):
            with patch.object(subject,'verify',return_value={'cold_consistent':False,'integrity_pass':True}):
                with self.assertRaisesRegex(RuntimeError,'COLD'):
                    subject.source_serial(Path('synthetic.zip'))

class UsbDiscovery(TestCase):
    @patch.object(subject,'source_serial',return_value=(OLD,{}, {},'/dev/serial/by-id/usb-SONOFF-example-if00'))
    @patch.object(subject,'load_ha')
    @patch.object(subject,'addon_info',return_value={'state':'started'})
    def test_refuses_while_addon_runs(self,_info,connection,_source):
        with self.assertRaisesRegex(RuntimeError,'not stopped or error'):
            subject.discover(Path('synthetic.zip'),TARGET)
        connection.return_value.exec_command.assert_not_called()

    @patch.object(subject,'source_serial',return_value=(OLD,{}, {},'/dev/serial/by-id/usb-SONOFF-example-if00'))
    @patch.object(subject,'load_ha')
    @patch.object(subject,'addon_info',return_value={'state':'stopped'})
    def test_verified_usb_revision_required(self,_info,connection,_source):
        client=connection.return_value
        stream=MagicMock();stream.read.return_value=json.dumps({'source_usb_absent':True,
            'verified_target_by_id':TARGET,'znp_p10_verified':True,'product':1,
            'revision':12345678}).encode()
        stream.channel.recv_exit_status.return_value=0
        client.exec_command.return_value=(None,stream,None)
        with patch.object(subject,'addon_quiescent',return_value={'addon_quiescent':True}):
            with self.assertRaisesRegex(RuntimeError,'not the previously measured'):
                subject.discover(Path('synthetic.zip'),TARGET)
        stream.read.return_value=json.dumps({'source_usb_absent':True,
            'verified_target_by_id':TARGET,'znp_p10_verified':True,'product':1,
            'revision':subject.EXPECTED_REVISION}).encode()
        with patch.object(subject,'addon_quiescent',return_value={'addon_quiescent':True}):
            self.assertTrue(subject.discover(Path('synthetic.zip'),TARGET)['znp_p10_verified'])

    def test_rejects_invalid_user_supplied_port_before_remote_access(self):
        with patch.object(subject,'source_serial',return_value=(OLD,{}, {},'/dev/serial/by-id/usb-S')):
            with self.assertRaises(ValueError): subject.discover(Path('synthetic.zip'),'COM4')
