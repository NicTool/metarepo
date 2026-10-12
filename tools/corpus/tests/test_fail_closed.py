# Copyright (c) 2026, The NicTool Contributors

import unittest

import anonymize

from tests.test_anonymize import SECRET, create_table, row_for


class FailClosedTests(unittest.TestCase):
    def test_distinct_short_labels_do_not_merge_record_owners(self):
        mapper = anonymize.Mapper(SECRET)
        labels = list('abcdefghijklnopqrstuvwxyz') + [a + b for a in 'abcde' for b in 'abcde']
        outputs = [mapper.label(label) for label in labels]
        self.assertEqual(len(labels), len(set(outputs)))
        self.assertEqual(outputs, [mapper.label(label) for label in labels])

    def test_distinct_source_tlds_do_not_merge_zones(self):
        mapper = anonymize.Mapper(SECRET)
        domains = ['fixture.' + tld for tld in ('com', 'net', 'org', 'co', 'io', 'uk', 'de')]
        self.assertEqual(len(domains), len({mapper.host(domain) for domain in domains}))

    def test_column_suffixes_are_parsed_completely(self):
        suffixes = (
            'DEFAULT "synthetic-secret-marker"',
            'DEFAULT (length("synthetic-secret-marker"))',
            "DEFAULT (length('synthetic-secret-marker'))",
            "DEFAULT 0x736563726574",
            "DEFAULT b'101010'",
            "GENERATED ALWAYS AS (123456789) STORED",
            "CHECK (123456789 = 123456789)",
            "COLLATE private_customer_collation",
            "CHARACTER SET private_customer_charset",
            "REFERENCES `private_customer` (`id`)",
            "UNRECOGNIZED private_customer",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix), self.assertRaises(anonymize.InputError):
                sql = create_table("nt_group").replace("`name` LONGTEXT NULL", "`name` LONGTEXT " + suffix)
                anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_index_expressions_cannot_copy_unchecked_content(self):
        for value in ('(length("synthetic-secret-marker"))', '`name`, (123456789)', '`name` private_customer'):
            with self.subTest(value=value), self.assertRaises(anonymize.InputError):
                sql = create_table("nt_group").replace("\n) ENGINE", f", KEY `index` ({value})\n) ENGINE")
                anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_malformed_ipv4_fields_fail_in_live_and_history_rows(self):
        values = ("8.9.10.11.12", "10.20.30.40.50.60", "08.9.10.11", "٨.9.10.11", "8..9", "8.256", "8.9.", "8", "-8.9")
        for table in ("nt_zone_record", "nt_zone_record_log"):
            for value in values:
                with self.subTest(table=table, value=value), self.assertRaises(anonymize.InputError):
                    fields = {"type_id": anonymize.Raw("1"), "address": value}
                    if table.endswith("_log"):
                        fields["action"] = "added"
                    sql = create_table(table) + f"\nINSERT INTO `{table}` VALUES " + row_for(table, **fields) + ";"
                    anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_audit_fragment_policy_rejects_invalid_octets(self):
        for value in ("10.2.3.4.5", "10.02.3.4", "١٠.2.3.4", "10.256"):
            with self.subTest(value=value):
                self.assertFalse(anonymize.mapped_ipv4_fragment(value.split(".")))

    def test_supported_ipv4_fragments_remain_consistent(self):
        mapper = anonymize.Mapper(SECRET)
        for value in ("8.9.10.11", "10.20.30.40", "172.17.4.5", "192.168.4.5", "169.254.4.5"):
            mapped = mapper.ip4_field(value)
            for count in (2, 3):
                self.assertEqual(".".join(mapped.split(".")[:count]), mapper.ip4_field(".".join(value.split(".")[:count])))
