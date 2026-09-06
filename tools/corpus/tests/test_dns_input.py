# Copyright (c) 2026, The NicTool Contributors

import tempfile
import unittest
from pathlib import Path

import anonymize
import dns_input

from tests.test_anonymize import SECRET, complete_dump, row_for


class DNSInputTests(unittest.TestCase):
    def test_private_pairing_preserves_table_order_and_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'source.sql')
            sql = complete_dump()
            for index in range(2, 6):
                row = row_for('nt_zone_record_log', nt_zone_record_log_id=anonymize.Raw(str(index)), type_id=anonymize.Raw('1'), address='8.9.10.11', action='added')
                sql += 'INSERT INTO `nt_zone_record_log` VALUES ' + row + ';\n'
            source.write_text(sql)
            source.chmod(0o600)
            corpus = Path(directory, 'corpus.sql.gz')
            anonymize.run(str(source), str(corpus), SECRET, 'fixture', retention_profile='historical-patterns')
            result = dns_input.build(str(corpus), str(Path(directory, 'corpus.manifest.json')), str(source))
            self.assertEqual(2, len(result['records']))
            for pair in result['records']:
                self.assertEqual(pair['before']['row']['nt_zone_record_log_id'], pair['after']['row']['nt_zone_record_log_id'])
                self.assertNotEqual(pair['before']['row']['address'], pair['after']['row']['address'])

    def test_failed_privacy_audit_prevents_dns_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'source.sql')
            source.write_text(complete_dump())
            source.chmod(0o600)
            corpus = Path(directory, 'corpus.sql.gz')
            anonymize.run(str(source), str(corpus), SECRET, 'fixture')
            source.write_text(complete_dump() + '\n')
            with self.assertRaises(anonymize.InputError):
                dns_input.build(str(corpus), str(Path(directory, 'corpus.manifest.json')), str(source))
