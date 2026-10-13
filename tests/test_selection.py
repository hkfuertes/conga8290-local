"""Account selection uses synthetic responses only; no network or APK."""
import unittest
from unittest.mock import patch

from conga8290.oem_rootless_client import RootlessClient

PRODUCT = 'kofl9ubyyyfznpxw'


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.client = RootlessClient(
            {'mAppId': 'synthetic-id', 'mAppVersion': '1.2.9',
             'mTtid': 'synthetic-ttid', 'mDeviceId': 'synthetic-client'},
            b'synthetic-material', '1234abcd', 'https://a1.tuyaeu.com', auth_flow='oem-ui')
        self.client.session = {'sid': 'synthetic-session', 'ecode': 'synthetic-ecode',
                               'mobile_api_url': 'https://a1.tuyaeu.com'}

    def test_two_reads_select_only_the_supported_robot_without_reference(self):
        devices = [{'devId': 'other', 'productId': 'another-product', 'localKey': 'must-not-select!'},
                   {'devId': 'wanted', 'productId': PRODUCT, 'name': 'Test robot', 'localKey': '0123456789abcdef'}]
        with patch('conga8290.oem_rootless_client.read_api', side_effect=[[{'gid': 123, 'name': 'Test home'}], devices]) as read:
            homes = self.client.list_homes()
            robots = self.client.list_robots(homes[0]['gid'])
            self.assertEqual(robots, [{'id': 'wanted', 'name': 'Test robot'}])
            self.assertEqual(self.client.select_robot('wanted'), {'id': 'wanted', 'local_key': '0123456789abcdef'})
            self.assertEqual(read.call_count, 2)
            self.assertEqual(self.client.read_attempts, 2)
        self.client.close()
        self.assertIsNone(self.client.session)
        self.assertEqual(self.client._robot_keys, {})

    def test_gid_must_come_from_home_list_and_reads_cannot_retry(self):
        with patch('conga8290.oem_rootless_client.read_api', side_effect=[[{'gid': '123'}], []]) as read:
            self.client.list_homes()
            with self.assertRaises(ValueError):
                self.client.list_robots('456')
            self.client.list_robots('123')
            for action in [self.client.list_homes, lambda: self.client.list_robots('123')]:
                with self.assertRaises(ValueError):
                    action()
            self.assertEqual(read.call_count, 2)

    def test_duplicate_supported_robot_id_fails_closed(self):
        device = {'devId': 'wanted', 'productId': PRODUCT, 'localKey': '0123456789abcdef'}
        with patch('conga8290.oem_rootless_client.read_api', side_effect=[[{'gid': 123}], [device, device]]):
            self.client.list_homes()
            with self.assertRaises(ValueError):
                self.client.list_robots('123')

    def test_arbitrary_id_cannot_export_a_key(self):
        with self.assertRaises(ValueError):
            self.client.select_robot('arbitrary')
