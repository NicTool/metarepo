# Copyright (c) 2026, The NicTool Contributors

import ipaddress
import json
import re
import tempfile
import unittest
from pathlib import Path

import anonymize
import audit
from schema import KNOWN_COLUMNS, SCHEMA_COLUMNS, STATIC_PROFILES, STRING_COLUMNS

SECRET = "fixture secret with more than thirty two bytes"


def create_table(table, columns=None, suffix="ENGINE=InnoDB"):
    columns = columns or KNOWN_COLUMNS[table]
    definitions = ",\n".join(f"  `{column}` {'LONGTEXT' if (table, column) in STRING_COLUMNS else 'BIGINT'} NULL" for column in columns)
    return f"CREATE TABLE `{table}` (\n{definitions}\n) {suffix};"


def sql_value(value):
    return value if isinstance(value, anonymize.Raw) else anonymize.sql_str(value)


def row_for(table, **values):
    row = ["" if (table, column) in STRING_COLUMNS else anonymize.Raw("0") for column in KNOWN_COLUMNS[table]]
    for name, value in values.items():
        row[KNOWN_COLUMNS[table].index(name)] = value
    return "(" + ",".join(sql_value(value) for value in row) + ")"


def complete_dump():
    statements = [create_table(table) for table in KNOWN_COLUMNS]
    statements.extend(
        (
            "INSERT INTO `nt_options` VALUES " + row_for("nt_options", option_id=anonymize.Raw("1"), option_name="db_version", option_value="2.41") + ";",
            "INSERT INTO `nt_user` VALUES " + row_for("nt_user", nt_user_id=anonymize.Raw("1"), nt_group_id=anonymize.Raw("1"), first_name="李", last_name="Li", username="real-user", password="old hash", pass_salt="old salt", email="real.user@private.invalid", is_admin=anonymize.Raw("1"), deleted=anonymize.Raw("0")) + ";",
            "INSERT INTO `nt_user_log` VALUES " + row_for("nt_user_log", nt_user_log_id=anonymize.Raw("1"), nt_group_id=anonymize.Raw("1"), nt_user_id=anonymize.Raw("1"), action="modified", timestamp=anonymize.Raw("1"), modified_user_id=anonymize.Raw("1"), first_name="李", last_name="Li", username="real-user", password="old hash", pass_salt="old salt", email="real.user@private.invalid") + ";",
            "INSERT INTO `nt_user_session` VALUES " + row_for("nt_user_session", nt_user_session_id=anonymize.Raw("1"), nt_user_id=anonymize.Raw("1"), nt_user_session="session-secret", last_access=anonymize.Raw("1")) + ";",
            "INSERT INTO `nt_user_session_log` VALUES " + row_for("nt_user_session_log", nt_user_session_log_id=anonymize.Raw("1"), nt_user_id=anonymize.Raw("1"), action="login", timestamp=anonymize.Raw("1"), nt_user_session_id=anonymize.Raw("1"), nt_user_session="session-secret") + ";",
        )
    )
    return "\n".join(statements) + "\n"


class RowParserTests(unittest.TestCase):
    def test_nested_expression_does_not_split_the_row(self):
        row, tail = anonymize.parse_row("(1,POINT(1,2),'tail'),next")

        self.assertEqual(["1", "POINT(1,2)", "tail"], row)
        self.assertEqual(",next", tail)

    def test_strings_support_doubled_quotes_and_mysqldump_escapes(self):
        value = "a''b\\0\\n\\r\\Z\\b\\t\\\\\\'\\\""
        row, tail = anonymize.parse_row(f"('{value}')")

        self.assertEqual("a'b\0\n\r\x1a\b\t\\'\"", row[0])
        self.assertEqual("", tail)
        self.assertEqual(row, anonymize.parse_row("(" + anonymize.sql_str(row[0]) + ")")[0])

    def test_unknown_escape_fails_closed(self):
        with self.assertRaisesRegex(anonymize.InputError, "unsupported.*escape"):
            anonymize.parse_row(r"('bad\qescape')")

    def test_one_line_and_multiline_insert_tuples_are_all_parsed(self):
        one_line = "INSERT INTO `nt_group` VALUES (1,0,'One',0),(2,1,'Two',0)"
        multiline = "INSERT INTO `nt_group` VALUES\n(1,0,'One',0),\n(2,1,'Two',0)"

        self.assertEqual(2, len(anonymize.parse_insert(one_line)[1]))
        self.assertEqual(anonymize.parse_insert(one_line), anonymize.parse_insert(multiline))

    def test_explicit_column_insert_is_rejected(self):
        with self.assertRaisesRegex(anonymize.InputError, "without a column list"):
            anonymize.parse_insert("INSERT INTO `nt_group` (`name`) VALUES ('private')")

    def test_literal_newline_is_escaped_on_output(self):
        row, _ = anonymize.parse_row("('line one\nline two')")

        self.assertEqual("'line one\\nline two'", anonymize.sql_str(row[0]))


class MapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = anonymize.Mapper("fixture secret with more than thirty two bytes")

    def test_distinct_usernames_stay_distinct(self):
        sources = [f"private-user-{index}" for index in range(500)]
        mapped = [self.mapper.username(source) for source in sources]

        self.assertEqual(len({name.casefold() for name in mapped}), len(sources))
        self.assertNotEqual(self.mapper.username("private-user-10"), self.mapper.username("private-user-14"))
        self.assertEqual(mapped[3], self.mapper.username("PRIVATE-USER-3"))
        self.assertNotIn("root", {name.casefold() for name in mapped})

    def test_relative_names_follow_their_zone(self):
        zone = self.mapper.host("example.com")
        self.assertEqual(self.mapper.record_host("foo.bar", "example.com") + "." + zone + ".", self.mapper.host("foo.bar.example.com."))
        self.assertEqual(self.mapper.record_host("www", "example.com") + "." + zone, self.mapper.host("www.example.com"))
        self.assertEqual(self.mapper.record_host("www.example.com", "example.com"), self.mapper.host("www.example.com"))
        self.assertEqual(self.mapper.record_host("other.net.", "example.com"), self.mapper.host("other.net."))
        for value in ("@", "*", ""):
            self.assertEqual(value, self.mapper.record_host(value, "example.com"))

    def test_single_label_zone_is_the_suffix_of_its_names(self):
        zone = self.mapper.host("lan")
        self.assertTrue(self.mapper.host("printer.lan.").endswith("." + zone + "."))
        self.assertEqual(self.mapper.record_host("printer", "lan") + "." + zone + ".", self.mapper.host("printer.lan."))

    def test_spf_ip6_mechanisms_stay_addresses(self):
        mapped = self.mapper.txt("v=spf1 ip6:2001:4860::/32 ip4:203.0.113.5 -all", {})

        self.assertRegex(mapped, r"^v=spf1 ip6:2001:db8:[0-9a-f:]+/32 ip4:[0-9.]+ -all$")
        self.assertNotIn("4860", mapped)

    def test_ip6_reverse_zones_contain_their_mapped_addresses(self):
        for address in ("2001:4860:1234:5678::1", "fd12:3456::1", "fe80::1"):
            with self.subTest(address=address):
                owner = ipaddress.IPv6Address(address).reverse_pointer + "."
                zone = ".".join(owner.split(".")[16:])
                mapped_owner = ipaddress.IPv6Address(self.mapper.ip6(address)).reverse_pointer + "."
                self.assertEqual(mapped_owner, self.mapper.host(owner))
                self.assertTrue(mapped_owner.endswith("." + self.mapper.host(zone)))
                relative = self.mapper.record_host(".".join(owner.split(".")[:16]), zone.rstrip("."))
                self.assertRegex(relative, r"^([0-9a-f]\.){15}[0-9a-f]$")

    def test_distinct_ip4_prefixes_stay_distinct(self):
        sources = [f"{first}.{second}.7" for first in range(1, 9) for second in range(40)]
        mapped = [self.mapper.ip4_prefix(source, 3) for source in sources]
        addresses = {self.mapper.ip4(f"{source}.9") for source in sources}

        self.assertEqual(len(set(mapped)), len(sources))
        self.assertEqual(len(addresses), len(sources))
        self.assertEqual({address.rsplit(".", 1)[0] for address in addresses}, set(mapped))

    def test_public_ip4_prefixes_that_cannot_fit_stop_the_run(self):
        with self.assertRaisesRegex(anonymize.InputError, "IPv4 prefixes collide"):
            for first in range(1, 9):
                self.mapper.ip4_prefix(f"{first}.1", 2)

    def test_opaque_underscore_label_is_replaced(self):
        source = "_93eb26a4e9cb12d915d090befff63c6c"
        mapped = self.mapper.label(source)

        self.assertTrue(mapped.startswith("_"))
        self.assertNotEqual(source, mapped)
        self.assertNotRegex(mapped, r"[0-9a-f]{16}")

    def test_protocol_underscore_labels_are_explicitly_preserved(self):
        for label in ("_dmarc", "_domainkey", "_acme-challenge", "_tcp", "_udp"):
            with self.subTest(label=label):
                self.assertEqual(label, self.mapper.label(label))

    def test_wildcard_maps_the_same_in_fields_and_free_text(self):
        source = "*.private.example.net."

        self.assertEqual(self.mapper.host(source), self.mapper.scrub(source))
        self.assertTrue(self.mapper.host(source).startswith("*."))

    def test_address_labels_and_reverse_zone_use_the_address_mapping(self):
        source = "52.13.20.9"
        mapped = self.mapper.ip4(source)

        self.assertTrue(self.mapper.host(source + ".mail.private.net.").startswith(mapped + "."))
        expected_reverse = ".".join(reversed(mapped.split("."))) + ".in-addr.arpa."
        self.assertEqual(expected_reverse, self.mapper.host("9.20.13.52.in-addr.arpa."))

    def test_internal_record_targets_map_to_the_mapped_zone(self):
        zone = self.mapper.host("private.example.net.")
        record = self.mapper.label("origin") + "." + zone

        self.assertEqual(record, self.mapper.host("origin.private.example.net."))
        self.assertNotEqual("outside.provider.net.", self.mapper.host("outside.provider.net."))

    def test_addresses_are_replaced_within_their_source_class(self):
        for source in (
            "169.254.12.34",
            "10.23.45.67",
            "52.13.20.9",
            "fe80::1234",
            "fd12:3456::8",
            "2001:4860:4860::8888",
        ):
            with self.subTest(source=source):
                mapped = self.mapper.ip6(source) if ":" in source else self.mapper.ip4(source)
                self.assertNotEqual(source, mapped)

        self.assertEqual("0.0.0.0", self.mapper.ip4("0.0.0.0"))
        self.assertEqual("127.0.0.1", self.mapper.ip4("127.0.0.1"))
        self.assertEqual("::", self.mapper.ip6("::"))
        self.assertEqual("::1", self.mapper.ip6("::1"))

        ipv4_cases = {
            "10.23.45.67": "10.0.0.0/8",
            "172.20.45.67": "172.16.0.0/12",
            "192.168.45.67": "192.168.0.0/16",
            "169.254.12.34": "169.254.0.0/16",
            "127.2.3.4": "127.0.0.0/8",
            "100.70.8.9": "100.64.0.0/10",
            "224.1.2.3": "233.252.0.0/24",
            "52.13.20.9": "198.18.0.0/15",
        }
        for source, network in ipv4_cases.items():
            with self.subTest(source=source):
                self.assertIn(ipaddress.ip_address(self.mapper.ip4(source)), ipaddress.ip_network(network))

        ipv6_cases = {
            "fe80::1234": "fe80::/10",
            "fd12:3456::8": "fd00::/8",
            "fec0::1234": "fec0::/10",
            "ff05::1234": "ff05::/16",
            "2001:4860:4860::8888": "2001:db8::/32",
        }
        for source, network in ipv6_cases.items():
            with self.subTest(source=source):
                self.assertIn(ipaddress.ip_address(self.mapper.ip6(source)), ipaddress.ip_network(network))

    def test_address_mapping_cannot_return_source_host_bits(self):
        ipv4 = anonymize.Mapper(SECRET)

        def same_octet(kind, value, low, high):
            source = int(value.rsplit(".", 1)[-1])
            return source if low <= source <= high else low

        ipv4.oracle.integer = same_octet
        self.assertNotEqual("10.23", ipv4.ip4_prefix("10.23", 2))
        self.assertNotEqual("10.23.45.67", ipv4.ip4("10.23.45.67"))

        ipv6 = anonymize.Mapper(SECRET)
        source = ipaddress.IPv6Address("fd12:3456::8")
        ipv6.oracle.bytes = lambda kind, value, size=32: int(source).to_bytes(16, "big")
        self.assertNotEqual(str(source), ipv6.ip6(str(source)))

    def test_compressed_ipv6_and_address_fragments_are_scrubbed(self):
        text = "from fe80::1234 and 198.9 then ip4:52.13.20"
        mapped = self.mapper.scrub(text)

        self.assertNotIn("fe80::1234", mapped)
        self.assertNotIn("198.9", mapped)
        self.assertNotIn("52.13.20", mapped)

    def test_typed_address_fields_map_fragments_and_reject_invalid_values(self):
        self.assertRegex(self.mapper.ip4_field("52.13.20"), r"^198\.1[89]\.\d{1,3}$")
        self.assertRegex(self.mapper.ip4_field("10.20.30"), r"^10\.\d{1,3}\.\d{1,3}$")
        self.assertNotEqual("2001:4860::1", self.mapper.ip6_field("2001:4860::1"))
        for function, value in ((self.mapper.ip4_field, "300.1.2.3"), (self.mapper.ip4_field, "address"), (self.mapper.ip6_field, "2001:::1")):
            with self.subTest(value=value), self.assertRaisesRegex(anonymize.InputError, "unsupported"):
                function(value)

    def test_txt_fragments_formed_after_restoring_split_text_are_remapped(self):
        source = r"x=xxx1 xx1\11111.111.11.11 xxxxxxx\111xxxx.xxxxxxxxx.xxx xxxxxxx\111xx1.xxxxxxxxx.xxx ~xxx"

        mapped = self.mapper.txt(source)
        fragments = [candidate.split(".") for candidate in self.mapper.IP4_RE.findall(mapped) if len(candidate.split(".")) < 4]

        self.assertTrue(fragments)
        self.assertTrue(all(anonymize.mapped_ipv4_fragment(parts) for parts in fragments))
        self.assertIn("0.0.0.0", self.mapper.txt("v=spf1 ip4:0.0.0.0 -all"))

    def test_unicode_and_short_words_are_replaced(self):
        words = "李 Ö Я Dr Li at HQ"
        source = words + " 7 42"
        mapped = self.mapper.words(source)

        self.assertNotEqual(source, mapped)
        for word in words.split():
            self.assertNotIn(word, mapped)
        self.assertNotEqual(["7", "42"], mapped.split()[-2:])

    def test_dkim_variants_replace_all_key_material(self):
        variants = (
            "V=DKIM1; P=AbCdEf12",
            'v=DKIM1; p="AbCd" "Ef12"',
            "v=DKIM1; p=Ab CDef 12",
            "p=short",
        )
        for source in variants:
            with self.subTest(source=source):
                mapped = self.mapper.txt(source)
                self.assertNotIn("AbCdEf12", mapped.replace('"', "").replace(" ", ""))
                self.assertNotIn("short", mapped)

    def test_short_and_mixed_separator_tokens_are_replaced(self):
        for source in ("short-secret-123456", "abcdefghij:klmnopqrst", "abc.def_ghi-jkl"):
            with self.subTest(source=source):
                mapped = self.mapper.txt(source)
                self.assertNotIn(source, mapped)

    def test_each_opaque_token_run_has_an_audit_marker(self):
        mapped = self.mapper._opaque("token", "alpha-beta_gamma:delta")

        self.assertTrue(all(part.startswith("Q") for part in re.findall(r"[A-Za-z0-9]+", mapped)))

    def test_short_unicode_txt_text_is_replaced_but_protocol_words_remain(self):
        mapped = self.mapper.txt("v=spf1 李 x include:private.invalid -all")

        self.assertIn("v=spf1", mapped)
        self.assertIn("include:", mapped)
        self.assertIn("-all", mapped)
        self.assertNotIn("李", mapped)
        self.assertNotRegex(mapped, r"\bx\b")
        self.assertNotIn("private.invalid", mapped)

    def test_verification_key_keeps_its_name_and_replaces_its_value(self):
        mapped = self.mapper.txt("google-site-verification=short")

        self.assertTrue(mapped.startswith("google-site-verification=Q"))
        self.assertNotIn("short", mapped)

    def test_people_do_not_fragment_structured_text(self):
        people = (("site", "Reyes"), ("short", "Alex"), ("invalid", "Morgan"))
        mapped = self.mapper.txt('person@site.invalid google-site-verification=short v=DKIM1; p="AbCd" "Ef12"', people)

        email = self.mapper.EMAIL_RE.search(mapped).group(0)
        self.assertTrue(email.rsplit("@", 1)[1].endswith((".test", ".example")))
        self.assertRegex(mapped, r"google-site-verification=Q")
        self.assertNotIn("AbCd", mapped)
        self.assertNotIn("Ef12", mapped)

    def test_dmarc_policy_is_not_treated_as_dkim_material(self):
        mapped = self.mapper.txt("v=DMARC1; p=reject; rua=mailto:admin@private.invalid")

        self.assertIn("v=DMARC1", mapped)
        self.assertIn("p=reject", mapped)
        self.assertNotIn("private.invalid", mapped)

    def test_microsoft_verification_keeps_its_shape_and_has_a_marker(self):
        mapped = self.mapper.txt("MS = ms12345678")

        self.assertRegex(mapped, r"MS = ms0\d{7}")
        self.assertNotIn("12345678", mapped)

    def test_loc_coordinates_are_valid_and_replaced(self):
        source = "37 47 0.125 N 122 24 0.500 W 10.25m 1m 10000m 10m"
        mapped = self.mapper.loc(source)

        self.assertEqual("51 30 0.000 N 0 7 0.000 W 100.00m 1m 10000m 10m", mapped)
        self.assertIsNotNone(self.mapper.LOC_RE.fullmatch(mapped))
        self.assertNotIn("37 47", mapped)

        with self.assertRaisesRegex(anonymize.InputError, "invalid LOC"):
            self.mapper.loc("91 0 0 N 0 0 0 E 0m")

    def test_generated_key_and_token_material_does_not_look_like_der(self):
        for source in ("p=MIIByDCCAXACAQAw", "token-which-is-secret"):
            with self.subTest(source=source):
                mapped = self.mapper.txt(source)
                opaque = mapped.split("=", 1)[-1].replace(" ", "").replace('"', "")
                self.assertFalse(opaque.startswith("M"))

    def test_mapping_fixed_points_are_changed(self):
        self.assertNotEqual("q", self.mapper.label("q"))
        self.assertNotEqual("Alex", self.mapper.first("Alex"))
        self.assertNotEqual("Reyes", self.mapper.last("Reyes"))

        username = anonymize.Mapper(SECRET)
        username.oracle.pick = lambda kind, value, choices: "" if kind == "user-number" else "alex"
        self.assertNotEqual("alex", username.username("alex"))

        opaque = anonymize.Mapper(SECRET)
        opaque.oracle.pick = lambda kind, value, choices: "Q"
        self.assertNotEqual("Q", opaque._opaque("token", "Q"))
        self.assertTrue(opaque._opaque("token", "Q").startswith("Q"))

        self.assertNotEqual("root@localhost.test", self.mapper.email("root@localhost.test"))
        self.assertEqual("root@localhost.test", self.mapper.email("root@localhost"))

        source = "51 30 0 N 0 7 0 W 100m"
        self.assertEqual("51 31 0 N 0 7 0 W 100m", self.mapper.loc(source))

    def test_generated_names_and_labels_avoid_all_reserved_source_values(self):
        mapper = anonymize.Mapper(SECRET, {"alex", "reyes", "qa", "q"})

        self.assertNotIn(mapper.first("source").casefold(), mapper.reserved)
        self.assertNotIn(mapper.last("source").casefold(), mapper.reserved)
        self.assertNotIn(mapper.username("source").casefold(), mapper.reserved)
        self.assertNotIn(mapper.label("word").casefold(), mapper.reserved)
        self.assertNotIn(mapper.label("x").casefold(), mapper.reserved)


class DumpContractTests(unittest.TestCase):
    def test_unknown_table_stops_the_run(self):
        sql = "CREATE TABLE `nt_surprise` (`id` int);"

        with self.assertRaisesRegex(anonymize.InputError, "unknown table"):
            anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_unknown_or_missing_column_stops_the_run(self):
        sql = create_table("nt_group", ("nt_group_id", "parent_group_id", "name"))

        with self.assertRaisesRegex(anonymize.InputError, "unknown or missing column"):
            anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_unsupported_sql_routine_trigger_and_definer_stop_the_run(self):
        cases = {
            "unsupported": "UPDATE `nt_group` SET `name`='private';",
            "routine": "CREATE PROCEDURE p() SELECT 1;",
            "trigger": "CREATE TRIGGER t BEFORE INSERT ON `nt_group` FOR EACH ROW SET @x=1;",
            "definer": "CREATE DEFINER=`person`@`host` VIEW v AS SELECT 1;",
            "delimiter": "DELIMITER ;;\nCREATE PROCEDURE p() SELECT 1;;\nDELIMITER ;",
        }
        for label, sql in cases.items():
            with self.subTest(label=label), self.assertRaises(anonymize.InputError):
                anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_dump_headers_are_removed_instead_of_copied(self):
        sql = "-- Host: production.example    Database: private\n-- Server version 10.11\nALTER DATABASE `private` CHARACTER SET latin1 COLLATE latin1_swedish_ci;\n" + create_table("nt_group")

        output, _ = anonymize.anonymize_sql(sql, SECRET, require_complete=False)

        self.assertNotIn("production", output)
        self.assertNotIn("Server version", output)
        self.assertNotIn("ALTER DATABASE", output)

    def test_create_metadata_is_removed_or_rejected(self):
        statement = create_table("nt_group", suffix="ENGINE=InnoDB AUTO_INCREMENT=123")
        statement = statement.replace("\n) ENGINE", ",\n  KEY `customer_index` (`name`)\n) ENGINE")

        output, _ = anonymize.anonymize_sql(statement, SECRET, require_complete=False)

        self.assertNotIn("customer_index", output)
        self.assertNotIn("AUTO_INCREMENT", output)
        self.assertIn("KEY `ix_nt_group_1`", output)

        unsafe = create_table("nt_group").replace("LONGTEXT NULL", "LONGTEXT DEFAULT 'customer-name'", 1)
        with self.assertRaisesRegex(anonymize.InputError, "non-allowlisted string literal"):
            anonymize.anonymize_sql(unsafe, SECRET, require_complete=False)

        for value in ("203.0.113.17", "+1 555 0100", "2001:db8::1", "5550100"):
            unsafe = create_table("nt_group").replace("LONGTEXT NULL", f"LONGTEXT DEFAULT '{value}'", 1)
            with self.assertRaisesRegex(anonymize.InputError, "non-allowlisted string literal"):
                anonymize.anonymize_sql(unsafe, SECRET, require_complete=False)

        unknown_option = create_table("nt_group", suffix="ENGINE=InnoDB STORAGE DISK")
        with self.assertRaisesRegex(anonymize.InputError, "unsupported table options"):
            anonymize.anonymize_sql(unknown_option, SECRET, require_complete=False)

    def test_column_type_class_must_match_the_known_schema(self):
        string_as_number = create_table("nt_group").replace("`name` LONGTEXT", "`name` BIGINT")
        number_as_string = create_table("nt_group").replace("`nt_group_id` BIGINT", "`nt_group_id` LONGTEXT")

        for statement in (string_as_number, number_as_string):
            with self.subTest(statement=statement), self.assertRaisesRegex(anonymize.InputError, "unexpected SQL type"):
                anonymize.anonymize_sql(statement, SECRET, require_complete=False)

    def test_inline_foreign_key_names_are_replaced(self):
        statement = create_table("nt_group")
        statement = statement.replace(
            "\n) ENGINE",
            ",\n  CONSTRAINT `customer_fk` FOREIGN KEY (`parent_group_id`) "
            "REFERENCES `nt_group` (`nt_group_id`) ON DELETE CASCADE\n) ENGINE",
        )

        output, _ = anonymize.anonymize_sql(statement, SECRET, require_complete=False)

        self.assertNotIn("customer_fk", output)
        self.assertIn("CONSTRAINT `ix_nt_group_1`", output)

    def test_alter_foreign_keys_carry_only_known_columns(self):
        alter = "ALTER TABLE `nt_group` ADD CONSTRAINT `customer_fk` FOREIGN KEY ({}) REFERENCES `nt_group` ({}) ON DELETE CASCADE;"
        safe = create_table("nt_group") + "\n" + alter.format("`parent_group_id`", "`nt_group_id`")

        output, _ = anonymize.anonymize_sql(safe, SECRET, require_complete=False)

        self.assertIn("FOREIGN KEY (`parent_group_id`) REFERENCES `nt_group` (`nt_group_id`)", output)
        self.assertNotIn("customer_fk", output)
        for local, remote in (("`parent_group_id` customer_secret", "`nt_group_id`"), ("`parent_group_id`, `deleted`", "`nt_group_id`")):
            with self.subTest(local=local), self.assertRaises(anonymize.InputError):
                anonymize.anonymize_sql(create_table("nt_group") + "\n" + alter.format(local, remote), SECRET, require_complete=False)

    def test_caa_tags_and_root_targets_survive(self):
        records = ",".join(
            (
                row_for("nt_zone_record", nt_zone_record_id=anonymize.Raw("1"), nt_zone_id=anonymize.Raw("7"), name="@", type_id=anonymize.Raw("257"), address="private-ca.example", other="issue"),
                row_for("nt_zone_record", nt_zone_record_id=anonymize.Raw("2"), nt_zone_id=anonymize.Raw("7"), name="@", type_id=anonymize.Raw("15"), address="."),
            )
        )
        sql = create_table("nt_zone_record") + "\nINSERT INTO `nt_zone_record` VALUES " + records + ";\n"

        output, _ = anonymize.anonymize_sql(sql, SECRET, require_complete=False)

        self.assertIn("'issue'", output)
        self.assertNotIn("private-ca", output)
        self.assertIn("'.'", output)

    def test_relative_soa_mailbox_stays_relative(self):
        zone = row_for("nt_zone", nt_zone_id=anonymize.Raw("1"), zone="private.example", mailaddr="hostmaster")
        sql = create_table("nt_zone") + "\nINSERT INTO `nt_zone` VALUES " + zone + ";\n"

        output, _ = anonymize.anonymize_sql(sql, SECRET, require_complete=False)

        self.assertIn("'hostmaster'", output)

    def test_zones_that_map_to_one_name_stop_the_run(self):
        zones = ",".join(
            row_for("nt_zone", nt_zone_id=anonymize.Raw(str(index)), zone=zone)
            for index, zone in enumerate(("0.6.8.4.1.0.0.2.ip6.arpa", "0.2.0.2.1.0.0.2.ip6.arpa"), 1)
        )
        sql = create_table("nt_zone") + "\nINSERT INTO `nt_zone` VALUES " + zones + ";\n"

        with self.assertRaisesRegex(anonymize.InputError, "distinct zones map to the same name"):
            anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_non_allowlisted_static_row_stops_the_run(self):
        sql = create_table("resource_record_type") + "\nINSERT INTO `resource_record_type` VALUES (65000,'PRIVATE','private value',0,0,0);\n"

        with self.assertRaisesRegex(anonymize.InputError, "non-allowlisted"):
            anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_non_allowlisted_enum_value_stops_the_run(self):
        sql = create_table("nt_delegate") + "\nINSERT INTO `nt_delegate` VALUES " + row_for("nt_delegate", nt_object_type="CLIENT") + ";\n"

        with self.assertRaisesRegex(anonymize.InputError, "non-allowlisted static value"):
            anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_mapped_free_text_respects_column_length(self):
        table = create_table("nt_user_global_log").replace("`description` LONGTEXT", "`description` VARCHAR(6)")
        row = row_for(
            "nt_user_global_log",
            action="modified",
            object="user",
            target="user",
            target_name="x",
            title="x",
            description="x.io x",
        )

        output, manifest = anonymize.anonymize_sql(table + "\nINSERT INTO `nt_user_global_log` VALUES " + row + ";\n", SECRET, require_complete=False)
        items = anonymize.parse_dump(output, require_complete=False)
        mapped = next(payload[0] for kind, name, payload in items if kind == "insert" and name == "nt_user_global_log")
        description = mapped[KNOWN_COLUMNS["nt_user_global_log"].index("description")]

        self.assertLessEqual(len(description), 6)
        self.assertEqual(1, manifest["mapped"]["truncated_text"])

    def test_relational_name_that_exceeds_column_length_stops_the_run(self):
        table = create_table("nt_zone").replace("`zone` LONGTEXT", "`zone` VARCHAR(3)")
        row = row_for("nt_zone", zone="a.b", mailaddr="", description="", location="")

        with self.assertRaisesRegex(anonymize.InputError, "mapped value exceeds nt_zone.zone"):
            anonymize.anonymize_sql(table + "\nINSERT INTO `nt_zone` VALUES " + row + ";\n", SECRET, require_complete=False)

    def test_nameserver_permission_id_list_is_preserved(self):
        sql = create_table("nt_perm") + "\nINSERT INTO `nt_perm` VALUES " + row_for("nt_perm", perm_name="private permission", usable_ns="1,2,7") + ";\n"

        output, _ = anonymize.anonymize_sql(sql, SECRET, require_complete=False)

        self.assertIn("'1,2,7'", output)
        self.assertNotIn("private permission", output)

    def test_complete_schema_is_required_by_default(self):
        with self.assertRaisesRegex(anonymize.InputError, "not a complete"):
            anonymize.anonymize_sql(create_table("nt_group"), SECRET)

    def test_234_schema_profile_preserves_its_missing_zone_log_location(self):
        statement = create_table("nt_zone_log", SCHEMA_COLUMNS["2.34"]["nt_zone_log"])

        output, manifest = anonymize.anonymize_sql(statement, SECRET, require_complete=False, db_version="2.34")

        self.assertNotIn("`location`", output)
        self.assertEqual("2.34", manifest["input_contract"]["db_version"])
        with self.assertRaisesRegex(anonymize.InputError, "unknown or missing column"):
            anonymize.anonymize_sql(statement, SECRET, require_complete=False, db_version="2.41")

    def test_db_version_option_must_match_the_selected_schema(self):
        row = row_for("nt_options", option_id=anonymize.Raw("1"), option_name="db_version", option_value="2.34")
        statement = create_table("nt_options") + "\nINSERT INTO `nt_options` VALUES " + row + ";\n"

        _, manifest = anonymize.anonymize_sql(statement, SECRET, require_complete=False, db_version="2.34")

        self.assertEqual("2.34", manifest["input_contract"]["db_version"])
        with self.assertRaisesRegex(anonymize.InputError, "expected NicTool db_version 2.41"):
            anonymize.anonymize_sql(statement, SECRET, require_complete=False, db_version="2.41")

    def test_historical_static_profile_is_explicit_and_version_scoped(self):
        rows = STATIC_PROFILES["2.34-2024-07-31"]["nt_nameserver_export_type"]
        statement = create_table("nt_nameserver_export_type") + "\n" + anonymize.render_insert("nt_nameserver_export_type", sorted(rows)) + "\n"

        output, manifest = anonymize.anonymize_sql(
            statement,
            SECRET,
            require_complete=False,
            db_version="2.34",
            static_profile="2.34-2024-07-31",
        )

        self.assertIn("INSERT INTO `nt_nameserver_export_type`", output)
        self.assertEqual("2.34-2024-07-31", manifest["static_lookup_profile"])
        with self.assertRaisesRegex(anonymize.InputError, "not valid"):
            anonymize.anonymize_sql(statement, SECRET, require_complete=False, db_version="2.41", static_profile="2.34-2024-07-31")

    def test_historical_retention_keeps_first_and_last_rows_of_each_shape(self):
        rows = [
            row_for(
                "nt_group_log",
                nt_group_log_id=anonymize.Raw(str(index)),
                nt_group_id=anonymize.Raw("1"),
                nt_user_id=anonymize.Raw("1"),
                action="added",
                timestamp=anonymize.Raw(str(index)),
                modified_group_id=anonymize.Raw("1"),
                parent_group_id=anonymize.Raw("0"),
                name="group",
            )
            for index in (4, 5, 6)
        ]
        sql = "\n".join((create_table("nt_group_log"), f"INSERT INTO `nt_group_log` VALUES {rows[0]},{rows[1]};", f"INSERT INTO `nt_group_log` VALUES {rows[2]};"))

        output, manifest = anonymize.anonymize_sql(sql, SECRET, require_complete=False, retention_profile="historical-patterns")
        items = anonymize.parse_dump(output, require_complete=False)
        retained = [row for kind, table, payload in items if kind == "insert" and table == "nt_group_log" for row in payload]

        self.assertEqual(["4", "6"], [str(row[0]) for row in retained])
        self.assertEqual(3, manifest["source_rows"]["nt_group_log"])
        self.assertEqual(2, manifest["rows"]["nt_group_log"])
        self.assertEqual({"nt_group_log": 1}, manifest["retention"]["dropped_rows"])

    def test_historical_retention_distinguishes_unusual_text_shapes(self):
        columns = KNOWN_COLUMNS["nt_group_log"]
        ordinary = anonymize.parse_row(row_for("nt_group_log", action="added", name="group"))[0]
        unusual = anonymize.parse_row(row_for("nt_group_log", action="added", name="李\nname"))[0]

        self.assertNotEqual(
            anonymize.retention_shape("nt_group_log", ordinary, columns),
            anonymize.retention_shape("nt_group_log", unusual, columns),
        )

    def test_historical_retention_distinguishes_dns_name_shapes(self):
        shapes = {
            anonymize._text_retention_shape("nt_zone_record_log", "name", value)
            for value in ("host.example.test", "*.example.test", "_opaque.example.test", "1.0.0.127.in-addr.arpa", "93eb26a4e9cb12d915d090befff63c6c")
        }

        self.assertEqual(5, len(shapes))

    def test_one_line_users_are_discovered_and_live_history_values_agree(self):
        user = row_for("nt_user", nt_user_id=anonymize.Raw("1"), nt_group_id=anonymize.Raw("1"), first_name="Å", last_name="李", username="xy", password="old", pass_salt="salt", email="xy@private.invalid", is_admin=anonymize.Raw("0"), deleted=anonymize.Raw("0"))
        other = row_for("nt_user", nt_user_id=anonymize.Raw("2"), nt_group_id=anonymize.Raw("1"), first_name="Q", last_name="Ö", username="zz", password="old", pass_salt="salt", email="zz@private.invalid", is_admin=anonymize.Raw("0"), deleted=anonymize.Raw("0"))
        history = row_for("nt_user_log", nt_user_log_id=anonymize.Raw("1"), nt_group_id=anonymize.Raw("1"), nt_user_id=anonymize.Raw("1"), action="modified", timestamp=anonymize.Raw("1"), modified_user_id=anonymize.Raw("1"), first_name="Å", last_name="李", username="xy", password="old", pass_salt="salt", email="xy@private.invalid")
        log = row_for("nt_user_global_log", nt_user_global_log_id=anonymize.Raw("1"), nt_user_id=anonymize.Raw("1"), timestamp=anonymize.Raw("1"), action="modified", object="user", object_id=anonymize.Raw("1"), target="user", target_id=anonymize.Raw("1"), target_name="Å 李", log_entry_id=anonymize.Raw("1"), title="Å 李 changed", description="xy from fe80::1")
        sql = "\n".join((create_table("nt_user"), create_table("nt_user_log"), create_table("nt_user_global_log"), f"INSERT INTO `nt_user` VALUES {user},{other};", f"INSERT INTO `nt_user_log` VALUES\n{history};", f"INSERT INTO `nt_user_global_log` VALUES {log};"))

        output, manifest = anonymize.anonymize_sql(sql, SECRET, require_complete=False)
        items = anonymize.parse_dump(output, require_complete=False)
        rows = {table: payload[0] for kind, table, payload in items if kind == "insert"}
        live = dict(zip(KNOWN_COLUMNS["nt_user"], rows["nt_user"]))
        old = dict(zip(KNOWN_COLUMNS["nt_user_log"], rows["nt_user_log"]))
        global_log = dict(zip(KNOWN_COLUMNS["nt_user_global_log"], rows["nt_user_global_log"]))

        for name in ("first_name", "last_name", "username", "email"):
            self.assertEqual(live[name], old[name])
        self.assertEqual("", old["password"])
        self.assertEqual("", old["pass_salt"])
        self.assertNotIn("Å", global_log["title"])
        self.assertNotIn("李", global_log["title"])
        self.assertNotIn("xy", global_log["description"])
        self.assertNotIn("fe80::1", global_log["description"])
        self.assertEqual(2, manifest["rows"]["nt_user"])

    def test_raw_literals_cannot_bypass_column_mapping(self):
        cases = (
            ("parent_group_id", "0x70726976617465"),
            ("parent_group_id", "b'1010'"),
            ("parent_group_id", "POINT(1,2)"),
            ("name", "0x70726976617465"),
        )
        for column, value in cases:
            row = row_for("nt_group", **{column: anonymize.Raw(value)})
            sql = create_table("nt_group") + "\nINSERT INTO `nt_group` VALUES " + row + ";\n"
            with self.subTest(column=column, value=value), self.assertRaisesRegex(anonymize.InputError, "raw SQL value"):
                anonymize.anonymize_sql(sql, SECRET, require_complete=False)

    def test_null_and_numeric_values_remain_supported(self):
        row = row_for("nt_group", nt_group_id=anonymize.Raw("1"), parent_group_id=anonymize.Raw("NULL"), name=anonymize.Raw("NULL"))
        sql = create_table("nt_group") + "\nINSERT INTO `nt_group` VALUES " + row + ";\n"

        output, _ = anonymize.anonymize_sql(sql, SECRET, require_complete=False)

        self.assertIn("(1,NULL,NULL,0)", output)

    def test_contributor_must_be_a_safe_alias(self):
        for contributor in ("person@example.test", "Two Words", "../name", "-name", "name-"):
            with self.subTest(contributor=contributor), self.assertRaisesRegex(anonymize.InputError, "lower-case alias"):
                anonymize.anonymize_sql(create_table("nt_group"), SECRET, contributor, require_complete=False)

        _, manifest = anonymize.anonymize_sql(create_table("nt_group"), SECRET, "safe_alias-2", require_complete=False)
        self.assertEqual("safe_alias-2", manifest["provenance"]["contributor"])

    def test_source_provenance_must_use_safe_values(self):
        with self.assertRaisesRegex(anonymize.InputError, "source alias"):
            anonymize.anonymize_sql(create_table("nt_group"), SECRET, require_complete=False, source_alias="private.example")
        with self.assertRaisesRegex(anonymize.InputError, "source date"):
            anonymize.anonymize_sql(create_table("nt_group"), SECRET, require_complete=False, source_date="30 August 2026")

        _, manifest = anonymize.anonymize_sql(
            create_table("nt_group"),
            SECRET,
            require_complete=False,
            source_alias="private-production",
            source_date="2026-08-30",
        )
        self.assertEqual("private-production", manifest["provenance"]["source_alias"])
        self.assertEqual("2026-08-30", manifest["provenance"]["source_date"])
        self.assertEqual("not retained", manifest["provenance"]["raw_source"])


class ArtifactTests(unittest.TestCase):
    def test_complete_run_is_deterministic_and_manifest_counts_are_exact(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            source = Path(first_dir, "source.sql")
            source.write_text(complete_dump(), encoding="utf8")
            source.chmod(0o600)
            first = Path(first_dir, "corpus.sql.gz")
            second_source = Path(second_dir, "source.sql")
            second_source.write_bytes(source.read_bytes())
            second_source.chmod(0o600)
            second = Path(second_dir, "corpus.sql.gz")

            first_manifest = anonymize.run(str(source), str(first), SECRET, "fixture")
            second_manifest = anonymize.run(str(second_source), str(second), SECRET, "fixture")

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(json.loads(Path(first_dir, "corpus.manifest.json").read_text()), first_manifest)
            self.assertEqual(1, first_manifest["rows"]["nt_user"])
            self.assertEqual(1, first_manifest["source_rows"]["nt_user_session"])
            self.assertEqual(1, first_manifest["dropped"]["rows"]["nt_user_session"])
            self.assertEqual(0o600, first.stat().st_mode & 0o777)
            self.assertEqual(0o600, Path(first_dir, "corpus.manifest.json").stat().st_mode & 0o777)

    def test_reduced_artifact_source_audit_reproduces_the_retention_plan(self):
        rows = [
            row_for("nt_group_log", nt_group_log_id=anonymize.Raw(str(index)), action="added", timestamp=anonymize.Raw(str(index)), name="group")
            for index in (4, 5, 6)
        ]
        source_text = complete_dump() + "\n".join(f"INSERT INTO `nt_group_log` VALUES {row};" for row in rows) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source.sql")
            corpus = Path(directory, "corpus.sql.gz")
            source.write_text(source_text, encoding="utf8")
            source.chmod(0o600)
            anonymize.run(str(source), str(corpus), SECRET, "fixture", retention_profile="historical-patterns")

            report = audit.audit_paths(
                str(corpus),
                str(Path(directory, "corpus.manifest.json")),
                source_path=str(source),
                require_source=True,
            )

        self.assertEqual("PASS", report["status"], report["failures"])
        self.assertEqual(2, report["rows"]["nt_group_log"])

    def test_input_error_does_not_replace_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source.sql")
            source.write_text("UPDATE `nt_group` SET `name`='private';\n", encoding="utf8")
            source.chmod(0o600)
            destination = Path(directory, "corpus.sql")
            manifest = Path(directory, "corpus.manifest.json")
            destination.write_text("keep", encoding="utf8")
            manifest.write_text("keep", encoding="utf8")

            with self.assertRaises(anonymize.InputError):
                anonymize.run(str(source), str(destination), SECRET, "fixture", force=True)

            self.assertEqual("keep", destination.read_text())
            self.assertEqual("keep", manifest.read_text())

    def test_source_and_secret_files_must_not_be_group_or_world_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source.sql")
            source.write_text(complete_dump(), encoding="utf8")
            source.chmod(0o644)
            with self.assertRaisesRegex(anonymize.InputError, "source dump must be mode 0600"):
                anonymize.run(str(source), str(Path(directory, "out.sql")), SECRET, "fixture")

            secret_file = Path(directory, "secret")
            secret_file.write_text(SECRET, encoding="utf8")
            secret_file.chmod(0o644)
            with self.assertRaisesRegex(anonymize.InputError, "secret file must be mode 0600"):
                anonymize.read_secret({}, str(secret_file))

    def test_destination_must_be_sql_and_must_not_replace_the_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source.sql")
            source.write_text(complete_dump(), encoding="utf8")
            source.chmod(0o600)

            with self.assertRaisesRegex(anonymize.InputError, "destination must end"):
                anonymize.run(str(source), str(Path(directory, "corpus.dump")), SECRET, "fixture")
            with self.assertRaisesRegex(anonymize.InputError, "different files"):
                anonymize.run(str(source), str(source), SECRET, "fixture", force=True)

            self.assertEqual(complete_dump(), source.read_text())


if __name__ == "__main__":
    unittest.main()
