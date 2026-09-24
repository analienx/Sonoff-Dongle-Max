"""Synthetic HA apply tests: no real Zigbee2MQTT runtime operations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import p10_ha_apply as app


def synthetic_stage(root:Path,cold=True,verified=True):
    root.mkdir()
    old_yaml=b'serial:\n  port: old\n  adapter: ember\n'
    new_yaml=b'serial:\n  port: tcp://192.168.1.2:7638\n  adapter: zstack\n'
    old_options={'addon_slug':app.ADDON,'options':{'serial':{'port':'old','adapter':'ember'},'mqtt':{'password':'test-secret'}}}
    new_options={'addon_slug':app.ADDON,'options':{'serial':{'port':'tcp://192.168.1.2:7638','adapter':'zstack'},'mqtt':{'password':'test-secret'}}}
    files={'rollback_configuration.yaml':old_yaml,'target_configuration.yaml':new_yaml,
           'rollback_addon_options.private.json':json.dumps(old_options).encode(),
           'target_addon_options.private.json':json.dumps(new_options).encode()}
    for name,content in files.items(): (root/name).write_bytes(content)
    (root/'cutover_state.private.json').write_text(json.dumps({
        'bundle_cold':cold,'bundle_integrity_pass':True,'target_znp_verified_from_ha':verified,
        'rollback_and_target_hashes':{n:app.digest(v) for n,v in files.items()}}))


class AppTests(unittest.TestCase):
    def test_hot_bundle_cannot_be_used_for_live_deployment(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'stage'; synthetic_stage(root,cold=False)
            with patch.object(app,'private_target',lambda p:Path(p)):
                with self.assertRaisesRegex(RuntimeError,'FINAL cold'):
                    app.stage_files(root,'target')

    def test_target_radio_verification_cannot_be_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'stage'; synthetic_stage(root,verified=False)
            with patch.object(app,'private_target',lambda p:Path(p)):
                with self.assertRaisesRegex(RuntimeError,'endpoint'):
                    app.stage_files(root,'target')

    def test_tampered_secret_bearing_option_file_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'stage'; synthetic_stage(root)
            (root/'target_addon_options.private.json').write_bytes(b'changed')
            with patch.object(app,'private_target',lambda p:Path(p)):
                with self.assertRaisesRegex(RuntimeError,'integrity mismatch'):
                    app.stage_files(root,'target')

    def test_wrong_approval_is_noop(self):
        with patch.object(app,'live_plan',side_effect=AssertionError('must never access HA')):
            with self.assertRaisesRegex(ValueError,'approval'):
                app.apply(Path('fake'),'target','wrong',[])

    def test_physical_attestation_required_for_target_and_rollback(self):
        with patch.object(app,'live_plan',side_effect=AssertionError('must never access HA')):
            with self.assertRaisesRegex(ValueError,'attestations'):
                app.apply(Path('fake'),'target',app.PHRASES['target'],['source-isolated'])
            with self.assertRaisesRegex(ValueError,'attestations'):
                app.apply(Path('fake'),'rollback',app.PHRASES['rollback'],['source-isolated'])

    def test_invalid_live_state_fails_before_remote_write(self):
        with patch.object(app,'live_plan',return_value={'safe_to_apply_config':False}),\
             patch.object(app,'load_ha',side_effect=AssertionError('must never access HA')):
            with self.assertRaisesRegex(RuntimeError,'differs'):
                app.apply(Path('fake'),'rollback',app.PHRASES['rollback'],['target-isolated'])


if __name__=='__main__': unittest.main()
