# Copyright (c) 2026, The NicTool Contributors

import base64
import collections
import json
import tempfile
import unittest
from pathlib import Path

import anonymize
import audit

from tests.test_anonymize import SECRET, complete_dump


class AuditTests(unittest.TestCase):
    def make_artifact(self, directory):
        source = Path(directory, "source.sql")
        source.write_text(complete_dump(), encoding="utf8")
        source.chmod(0o600)
        corpus = Path(directory, "corpus.sql.gz")
        anonymize.run(str(source), str(corpus), SECRET, "fixture")
        return corpus, Path(directory, "corpus.manifest.json")

    def test_generated_artifact_passes_every_generic_check(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest = self.make_artifact(directory)

            report = audit.audit_paths(str(corpus), str(manifest))

            self.assertEqual("PASS", report["status"])
            self.assertEqual({}, report["failures"])
            self.assertEqual(1, report["rows"]["nt_user"])

    def test_private_source_comparison_checks_every_mapped_field(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest = self.make_artifact(directory)
            source = Path(directory, "source.sql")

            report = audit.audit_paths(str(corpus), str(manifest), source_path=str(source))

            self.assertEqual("PASS", report["status"])
            self.assertEqual("provided", report["source_input"])
            self.assertGreater(report["counts"]["source_candidates"], 0)
            self.assertEqual(0, report["counts"]["source_global_matches"])

    def test_private_source_comparison_requires_the_manifest_source(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest_path = self.make_artifact(directory)
            source = Path(directory, "source.sql")
            source.write_text(source.read_text() + "\n", encoding="utf8")

            report = audit.audit_paths(str(corpus), str(manifest_path), source_path=str(source))

            self.assertEqual("FAIL", report["status"])
            self.assertEqual(1, report["failures"]["manifest_source_sha256_mismatch"])
            self.assertEqual(1, report["failures"]["manifest_source_bytes_mismatch"])

    def test_publication_source_gate_requires_the_private_source(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest = self.make_artifact(directory)

            report = audit.audit_paths(str(corpus), str(manifest), require_source=True)

            self.assertEqual("FAIL", report["status"])
            self.assertEqual(1, report["failures"]["source_file_required"])

    def test_manifest_row_and_checksum_mismatches_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest_path = self.make_artifact(directory)
            manifest = json.loads(manifest_path.read_text())
            manifest["rows"]["nt_user"] = 99
            manifest["corpus"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf8")

            report = audit.audit_paths(str(corpus), str(manifest_path))

            self.assertEqual("FAIL", report["status"])
            self.assertEqual(1, report["failures"]["manifest_row_count_mismatch"])
            self.assertEqual(1, report["failures"]["manifest_corpus_sha256_mismatch"])

    def test_known_indicator_file_is_literal_exhaustive_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest = self.make_artifact(directory)
            indicators = Path(directory, "indicators")
            indicators.write_text("SET NAMES\n", encoding="utf8")
            indicators.chmod(0o600)

            report = audit.audit_paths(str(corpus), str(manifest), str(indicators), require_indicators=True)

            self.assertEqual("FAIL", report["status"])
            self.assertEqual(1, report["counts"]["known_indicators"])
            self.assertEqual(1, report["failures"]["known_indicator_match"])

            indicators.chmod(0o644)
            with self.assertRaisesRegex(anonymize.InputError, "group or world"):
                audit.read_indicators(str(indicators))

    def test_known_indicators_use_decoded_strings_and_unicode_normalization(self):
        _, manifest = anonymize.anonymize_sql(complete_dump(), SECRET, "fixture")
        sql = complete_dump() + "INSERT INTO `nt_group` VALUES (1,0,'A\u030a''lias',0);\n"
        manifest["rows"]["nt_group"] = 1

        report = audit.audit_sql(sql, manifest, ["Å'LIAS"])

        self.assertEqual(1, report["counts"]["known_indicator_sql"])
        self.assertEqual(1, report["failures"]["known_indicator_match"])

    def test_indicator_matcher_reports_distinct_overlapping_literals(self):
        matches = audit._matched_indicators(("private.example", "example", "private.example"), ("PRIVATE.EXAMPLE",))

        self.assertEqual({0, 1}, matches)

    def test_known_indicators_cover_manifest_values(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest = self.make_artifact(directory)
            indicators = Path(directory, "indicators")
            indicators.write_text("fixture\n", encoding="utf8")
            indicators.chmod(0o600)

            report = audit.audit_paths(str(corpus), str(manifest), str(indicators))

            self.assertEqual(1, report["counts"]["known_indicator_manifest"])
            self.assertEqual(1, report["failures"]["known_indicator_match"])

    def test_candidate_classifiers_reject_unscrubbed_values(self):
        report = {"counts": collections.Counter(), "failures": {}}
        der = base64.b64encode(b"\x30\x10" + b"\0" * 16).decode()

        audit._scan_value(report, "nt_user_global_log", "description", "person@live.invalid from 8.8.8.8 and 52.13.20", "")
        audit._scan_value(report, "nt_zone", "zone", "_93eb26a4e9cb12d915d090befff63c6c.live.invalid.", "")
        audit._scan_value(report, "nt_zone_record", "address", f"v=DKIM1; p={der}; short-secret-123456", "16")

        for failure in (
            "email_outside_test_domains",
            "ipv4_outside_policy",
            "ipv4_fragment_outside_policy",
            "opaque_hex_dns_label",
            "dkim_key_not_marked_synthetic",
            "plausible_complete_der_key",
            "opaque_token_not_marked_synthetic",
        ):
            with self.subTest(failure=failure):
                self.assertIn(failure, report["failures"])

    def test_address_and_email_counts_are_classified_by_field_and_policy(self):
        report = {"counts": collections.Counter(), "failures": {}}

        audit._scan_value(report, "nt_nameserver", "address", "198.18.2.3", "")
        audit._scan_value(report, "nt_nameserver", "address6", "fd00::1", "")
        audit._scan_value(report, "nt_nameserver", "description", "prefix 198.19.2", "")
        audit._scan_value(report, "nt_user", "email", "alex@demo.example", "")

        self.assertEqual(1, report["classifications"]["ipv4"]["nt_nameserver.address:benchmark"])
        self.assertEqual(1, report["classifications"]["ipv6"]["nt_nameserver.address6:ula"])
        self.assertEqual(1, report["classifications"]["ipv4_fragment"]["nt_nameserver.description:benchmark"])
        self.assertEqual(1, report["classifications"]["email"]["nt_user.email:example"])
        self.assertEqual({}, report["failures"])

    def test_split_dkim_is_checked_once_as_one_key(self):
        report = {"counts": collections.Counter(), "failures": {}}
        value = anonymize.Mapper(SECRET).txt('v=DKIM1; p="AbCd" "EfGh"')

        audit._scan_value(report, "nt_zone_record", "address", value, "16")

        self.assertEqual({}, report["failures"])
        self.assertEqual(1, report["counts"]["dkim_keys"])

    def test_long_generated_word_is_not_mistaken_for_a_token(self):
        report = {"counts": collections.Counter(), "failures": {}}
        value = anonymize.Mapper(SECRET).txt("identifyingphrase")

        audit._scan_value(report, "nt_zone_record", "address", value, "16")

        self.assertEqual({}, report["failures"])

    def test_compound_generated_words_are_not_mistaken_for_a_token(self):
        report = {"counts": collections.Counter(), "failures": {}}
        value = anonymize.Mapper(SECRET).txt("private=phrase")

        audit._scan_value(report, "nt_zone_record_log", "address", value, "16")

        self.assertEqual({}, report["failures"])

    def test_allowlisted_protocol_pair_is_not_mistaken_for_a_token(self):
        report = {"counts": collections.Counter(), "failures": {}}

        audit._scan_value(report, "nt_zone_record", "address", "redirect=none ns=autoconfig v=Qabc123", "16")

        self.assertEqual({}, report["failures"])

    def test_microsoft_verification_requires_the_synthetic_marker(self):
        clean = {"counts": collections.Counter(), "failures": {}}
        unsafe = {"counts": collections.Counter(), "failures": {}}

        audit._scan_value(clean, "nt_zone_record", "address", "MS=ms01234567", "16")
        audit._scan_value(unsafe, "nt_zone_record", "address", "MS=ms12345678", "16")

        self.assertEqual({}, clean["failures"])
        self.assertEqual(1, unsafe["failures"]["microsoft_verification_not_marked_synthetic"])

    def test_provider_verification_requires_the_synthetic_marker(self):
        clean = {"counts": collections.Counter(), "failures": {}}
        unsafe = {"counts": collections.Counter(), "failures": {}}

        audit._scan_value(clean, "nt_zone_record", "address", "google-site-verification=Qabc-123", "16")
        audit._scan_value(unsafe, "nt_zone_record", "address", "google-site-verification=live-123", "16")

        self.assertEqual({}, clean["failures"])
        self.assertEqual(1, unsafe["failures"]["provider_verification_not_marked_synthetic"])

    def test_loc_values_require_the_synthetic_coordinates(self):
        clean = {"counts": collections.Counter(), "failures": {}}
        alternate = {"counts": collections.Counter(), "failures": {}}
        unsafe = {"counts": collections.Counter(), "failures": {}}
        unsafe_detail = {"counts": collections.Counter(), "failures": {}}

        audit._scan_value(clean, "nt_zone_record", "address", "51 30 0 N 0 7 0 W 100m", "29")
        audit._scan_value(alternate, "nt_zone_record", "address", "51 31 0 N 0 7 0 W 100m", "29")
        audit._scan_value(unsafe, "nt_zone_record_log", "address", "37 47 0 N 122 24 0 W 10m", "29")
        audit._scan_value(unsafe_detail, "nt_zone_record_log", "address", "51 30 1 N 0 7 2 W 99m 2m", "29")

        self.assertEqual({}, clean["failures"])
        self.assertEqual({}, alternate["failures"])
        self.assertEqual(1, unsafe["failures"]["loc_value_not_synthetic"])
        self.assertGreaterEqual(unsafe_detail["failures"]["loc_value_not_synthetic"], 1)

    def test_manifest_contract_and_compression_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus, manifest_path = self.make_artifact(directory)
            manifest = json.loads(manifest_path.read_text())
            manifest["format"] = 1
            manifest["license"] = "proprietary"
            manifest["copyright"] = "unknown"
            manifest["tool"]["version"] = "old"
            manifest["provenance"]["contributor"] = "person@example.test"
            manifest["provenance"]["source_alias"] = "private.example"
            manifest["provenance"]["source_date"] = "unknown"
            manifest["provenance"]["raw_source"] = "included"
            manifest["static_lookup_profile"] = "unknown"
            manifest["dropped"]["tables"] = []
            manifest["corpus"]["compressed"] = False
            manifest_path.write_text(json.dumps(manifest), encoding="utf8")

            report = audit.audit_paths(str(corpus), str(manifest_path))

            for failure in (
                "manifest_format",
                "manifest_license",
                "manifest_copyright",
                "manifest_tool",
                "manifest_contributor",
                "manifest_source_alias",
                "manifest_source_date",
                "manifest_raw_source",
                "manifest_static_lookup_profile",
                "manifest_dropped_tables",
                "manifest_compressed_mismatch",
            ):
                with self.subTest(failure=failure):
                    self.assertEqual(1, report["failures"][failure])

    def test_static_profile_must_match_the_schema_version(self):
        sql, manifest = anonymize.anonymize_sql(complete_dump(), SECRET, "fixture")
        manifest["static_lookup_profile"] = "2.34-2024-07-31"

        report = audit.audit_sql(sql, manifest)

        self.assertEqual(1, report["failures"]["manifest_static_lookup_profile"])

    def test_retention_manifest_must_match_row_count_differences(self):
        sql, manifest = anonymize.anonymize_sql(complete_dump(), SECRET, "fixture")
        manifest["retention"]["dropped_rows"] = {"nt_user_log": 1}

        report = audit.audit_sql(sql, manifest)

        self.assertEqual(1, report["failures"]["manifest_retention"])

    def test_publication_mode_requires_known_indicators(self):
        manifest = {"rows": {}}
        sql = ""

        report = audit.audit_sql(sql, manifest, require_indicators=True)

        self.assertEqual("FAIL", report["status"])
        self.assertEqual(1, report["failures"]["known_indicator_file_required"])

    def test_dump_comments_are_rejected(self):
        report = audit.audit_sql("-- anonymous but unsupported\n", {"rows": {}})

        self.assertEqual("FAIL", report["status"])
        self.assertEqual(1, report["failures"]["sql_comment"])


if __name__ == "__main__":
    unittest.main()
