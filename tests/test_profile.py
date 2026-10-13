"""YAML/profile checks only; no Home Assistant or LAN connection."""
from pathlib import Path
import unittest
import yaml

from conga8290.oem_rootless_client import CONGA_PRODUCT


class ProfileTests(unittest.TestCase):
    def test_profile_targets_the_same_supported_product_as_the_selector(self):
        profile = yaml.safe_load((Path(__file__).resolve().parents[1] / 'cecotec_conga8290_vacuum.yaml').read_text())
        self.assertEqual(profile['products'][0]['id'], CONGA_PRODUCT)
        self.assertEqual(profile['products'][0]['manufacturer'], 'Cecotec')
        self.assertEqual([item['entity'] for item in profile['entities']],
                         ['vacuum', 'button', 'sensor', 'sensor', 'sensor', 'select'])
