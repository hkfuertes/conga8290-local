"""YAML/profile checks only; no Home Assistant or LAN connection."""
from pathlib import Path
import unittest
import yaml

CONGA_PRODUCT = "kofl9ubyyyfznpxw"  # product id checked at cloud discovery


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = yaml.safe_load((Path(__file__).resolve().parents[1] /
                                      'cecotec_conga8290_vacuum.yaml').read_text())

    def test_profile_targets_the_same_supported_product_as_the_selector(self):
        profile = self.profile
        self.assertEqual(profile['products'][0]['id'], CONGA_PRODUCT)
        self.assertEqual(profile['products'][0]['manufacturer'], 'Cecotec')
        self.assertEqual([item['entity'] for item in profile['entities'][:6]],
                          ['vacuum', 'button', 'sensor', 'sensor', 'sensor', 'select'])

    def test_extension_primary_dp_names_match_entity_platforms(self):
        names = {'select': 'option', 'switch': 'switch', 'number': 'value',
                 'sensor': 'sensor', 'button': 'button'}
        for entity in self.profile['entities'][6:]:
            self.assertEqual(entity['dps'][0]['name'], names[entity['entity']])

    def test_extensions_are_optional_and_never_force_queries(self):
        for entity in self.profile['entities'][6:]:
            for dp in entity['dps']:
                self.assertIs(dp.get('optional'), True)
                self.assertFalse(dp.get('force', False))

    def test_selects_have_unique_display_options_and_wire_values(self):
        for entity in self.profile['entities']:
            if entity['entity'] != 'select':
                continue
            mapping = entity['dps'][0]['mapping']
            self.assertEqual(len(mapping), len({item['value'] for item in mapping}))
            self.assertEqual(len(mapping), len({item['dps_val'] for item in mapping}))

    def test_cleaning_dimensions_are_separate_and_wire_spellings_preserved(self):
        selects = {entity.get('name', entity.get('translation_key')): entity['dps'][0]
                   for entity in self.profile['entities'] if entity['entity'] == 'select'}
        self.assertEqual({name: selects[name]['id'] for name in
                          ['Work mode', 'Cleaning pattern', 'Mopping intensity', 'mopping']},
                         {'Work mode': 41, 'Cleaning pattern': 105,
                          'Mopping intensity': 53, 'mopping': 10})
        self.assertEqual({item['dps_val'] for item in selects['Cleaning pattern']['mapping']},
                         {'auto', 'clean_thoroughly', 'acrubbing', 'border', 'espiral', 'espiral_cuadrada'})

    def test_experimental_and_destructive_controls_disabled_by_default(self):
        guarded_ids = {4, 12, 13, 16, 18, 20, 22, 24, 36, 37, 38, 39, 42, 46, 47,
                       49, 50, 51, 52, 101, 103, 106, 109, 142, 143, 144, 145, 146}
        for entity in self.profile['entities']:
            if any(dp['id'] in guarded_ids for dp in entity['dps']):
                self.assertIs(entity.get('hidden'), True)
        ids = {dp['id'] for entity in self.profile['entities'] for dp in entity['dps']}
        self.assertTrue(guarded_ids <= ids)

    def test_telemetry_is_not_exposed_as_writable_controls(self):
        for entity in self.profile['entities']:
            for dp in entity['dps']:
                if dp['id'] in {17, 19, 21, 23, 29, 30, 31, 40, 43, 120, 128}:
                    self.assertEqual(entity['entity'], 'sensor')
                self.assertNotIn(dp['id'], {14, 15, 32, 33, 34, 35, 107, 110, 147})
        life = [dp for entity in self.profile['entities'] for dp in entity['dps']
                if dp['id'] in {17, 19, 21, 23}]
        self.assertEqual(len(life), 4)
        self.assertTrue(all(dp['unit'] == 'min' for dp in life))

    def test_sensor_enum_options_require_enum_device_class(self):
        # HA rejects these during registration, which can also break the
        # integration's receive loop if a failed entity stays registered.
        for entity in self.profile['entities']:
            if entity['entity'] != 'sensor':
                continue
            options = [item['value'] for dp in entity['dps']
                       for item in dp.get('mapping', []) if isinstance(item.get('value'), str)]
            if options:
                self.assertEqual(entity.get('class'), 'enum', entity.get('name'))
