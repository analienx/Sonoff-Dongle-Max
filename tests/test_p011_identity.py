import tempfile
import unittest
from pathlib import Path

from deploy.decode_p011_identity import decode_identity


class P011IdentityTests(unittest.TestCase):
    def test_decoder(self):
        payload = bytes([0xA1, 0, 1, 11, 1, 0]) + b"29270a5d303d" + bytes(range(16))
        decoded = decode_identity(payload)
        self.assertEqual(decoded["schema"], 1)
        self.assertEqual(decoded["profile"], 11)
        self.assertEqual(decoded["capabilities"], 1)
        self.assertEqual(decoded["source_commit_prefix"], "29270a5d303d")
        self.assertEqual(decoded["resource_profile_sha256_prefix"], bytes(range(16)).hex())

    def test_rejects_bad_length(self):
        with self.assertRaises(ValueError):
            decode_identity(b"\xa1\x00")

    def test_rejects_nonhex_commit(self):
        payload = bytes([0xA1, 0, 1, 11, 1, 0]) + b"zzzzzzzzzzzz" + bytes(16)
        with self.assertRaises(ValueError):
            decode_identity(payload)


if __name__ == "__main__":
    unittest.main()
