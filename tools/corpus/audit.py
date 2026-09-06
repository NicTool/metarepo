#!/usr/bin/env python3
# Copyright (c) 2026, The NicTool Contributors

"""Audit every parsed value and the manifest for an anonymized corpus."""

import argparse
import base64
import gzip
import hashlib
import ipaddress
import json
import os
import re
import stat
import unicodedata
from collections import Counter, deque

import anonymize
from schema import (
    DROP_ROWS,
    HOST_TYPES,
    KNOWN_COLUMNS,
    ROW_STRING_LITERALS,
    SCHEMA_COLUMNS,
    SCHEMA_STRING_COLUMNS,
    STATIC_PROFILE_VERSIONS,
    STATIC_PROFILES,
    STATIC_ROWS,
    STRING_COLUMNS,
    TXT_TYPES,
)

FRAGMENT_FIELDS = {
    ("nt_nameserver", "description"),
    ("nt_nameserver", "export_status"),
    ("nt_nameserver", "logdir"),
    ("nt_nameserver", "datadir"),
    ("nt_nameserver_export_log", "message"),
    ("nt_nameserver_log", "action"),
    ("nt_nameserver_log", "description"),
    ("nt_nameserver_log", "export_format"),
    ("nt_nameserver_log", "logdir"),
    ("nt_nameserver_log", "datadir"),
    ("nt_perm", "perm_name"),
    ("nt_user_global_log", "action"),
    ("nt_user_global_log", "object"),
    ("nt_user_global_log", "target"),
    ("nt_user_global_log", "target_name"),
    ("nt_user_global_log", "title"),
    ("nt_user_global_log", "description"),
    ("nt_zone", "description"),
    ("nt_zone", "location"),
    ("nt_zone_log", "action"),
    ("nt_zone_log", "description"),
    ("nt_zone_log", "location"),
    ("nt_zone_record", "address"),
    ("nt_zone_record", "description"),
    ("nt_zone_record", "location"),
    ("nt_zone_record", "other"),
    ("nt_zone_record_log", "action"),
    ("nt_zone_record_log", "address"),
    ("nt_zone_record_log", "description"),
    ("nt_zone_record_log", "location"),
    ("nt_zone_record_log", "other"),
}
HOST_FIELDS = {
    ("nt_nameserver", "name"),
    ("nt_nameserver_log", "name"),
    ("nt_zone", "zone"),
    ("nt_zone", "mailaddr"),
    ("nt_zone_log", "zone"),
    ("nt_zone_log", "mailaddr"),
    ("nt_zone_record", "name"),
    ("nt_zone_record_log", "name"),
}
VERIFICATION_KEYS = {
    "apple-domain-verification",
    "atlassian-domain-verification",
    "facebook-domain-verification",
    "google-domain-verification",
    "google-site-verification",
    "keybase-site-verification",
}
PERSONAL_FIELDS = {
    ("nt_delegate", "delegated_by_name"),
    ("nt_delegate_log", "nt_user_name"),
    ("nt_group", "name"),
    ("nt_group_log", "name"),
    ("nt_nameserver", "remote_login"),
    ("nt_nameserver", "rsync_user"),
    ("nt_user", "email"),
    ("nt_user", "first_name"),
    ("nt_user", "last_name"),
    ("nt_user", "pass_salt"),
    ("nt_user", "password"),
    ("nt_user", "username"),
    ("nt_user_log", "email"),
    ("nt_user_log", "first_name"),
    ("nt_user_log", "last_name"),
    ("nt_user_log", "pass_salt"),
    ("nt_user_log", "password"),
    ("nt_user_log", "username"),
}
WORDS_FIELDS = {
    ("nt_nameserver", "datadir"),
    ("nt_nameserver", "description"),
    ("nt_nameserver", "export_status"),
    ("nt_nameserver", "logdir"),
    ("nt_nameserver_export_log", "message"),
    ("nt_nameserver_log", "datadir"),
    ("nt_nameserver_log", "description"),
    ("nt_nameserver_log", "export_format"),
    ("nt_nameserver_log", "logdir"),
    ("nt_perm", "perm_name"),
    ("nt_user_global_log", "description"),
    ("nt_user_global_log", "target_name"),
    ("nt_user_global_log", "title"),
    ("nt_zone", "description"),
    ("nt_zone", "location"),
    ("nt_zone_log", "description"),
    ("nt_zone_log", "location"),
    ("nt_zone_record", "description"),
    ("nt_zone_record", "location"),
    ("nt_zone_record_log", "description"),
    ("nt_zone_record_log", "location"),
}
SOURCE_PROTOCOL_WORDS = anonymize.TXT_WORDS | anonymize.KEEP_LABELS | {
    "acme",
    "apple",
    "atlassian",
    "challenge",
    "dmarc",
    "domainkey",
    "domain",
    "facebook",
    "google",
    "keybase",
    "site",
    "tcp",
    "udp",
    "verification",
}
SOURCE_PUBLIC_LITERALS = set(SOURCE_PROTOCOL_WORDS)
for values in ROW_STRING_LITERALS.values():
    for value in values:
        SOURCE_PUBLIC_LITERALS.add(value.casefold())
        SOURCE_PUBLIC_LITERALS.update(word.casefold() for word in anonymize.Mapper.WORD_RE.findall(value))
for rows in STATIC_ROWS.values():
    for row in rows:
        for value in row:
            SOURCE_PUBLIC_LITERALS.add(str(value).casefold())
            SOURCE_PUBLIC_LITERALS.update(word.casefold() for word in anonymize.Mapper.WORD_RE.findall(str(value)))


def _failure(report, name, count=1):
    report["failures"][name] = report["failures"].get(name, 0) + count


def _failure_field(report, name, count=1):
    fields = report.setdefault("failure_fields", {})
    fields[name] = fields.get(name, 0) + count


def _classification(report, category, table, column, policy, count=1):
    classifications = report.setdefault("classifications", {})
    values = classifications.setdefault(category, Counter())
    key = f"{table}.{column}:{policy}"
    values[key] += count


def _normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _matched_indicators(indicators, texts):
    patterns = tuple(dict.fromkeys(_normalized(indicator) for indicator in indicators if _normalized(indicator)))
    if not patterns:
        return set()
    edges = [{}]
    failures = [0]
    outputs = [set()]
    for pattern_index, pattern in enumerate(patterns):
        state = 0
        for char in pattern:
            next_state = edges[state].get(char)
            if next_state is None:
                next_state = len(edges)
                edges[state][char] = next_state
                edges.append({})
                failures.append(0)
                outputs.append(set())
            state = next_state
        outputs[state].add(pattern_index)
    pending = deque(edges[0].values())
    while pending:
        state = pending.popleft()
        for char, next_state in edges[state].items():
            pending.append(next_state)
            fallback = failures[state]
            while fallback and char not in edges[fallback]:
                fallback = failures[fallback]
            failures[next_state] = edges[fallback].get(char, 0)
            outputs[next_state].update(outputs[failures[next_state]])
    matched = set()
    for text in texts:
        state = 0
        for char in _normalized(text):
            while state and char not in edges[state]:
                state = failures[state]
            state = edges[state].get(char, 0)
            matched.update(outputs[state])
    return matched


def _valid_der_sequence(data):
    if len(data) < 2 or data[0] != 0x30:
        return False
    length = data[1]
    if length < 0x80:
        return length + 2 == len(data)
    size = length & 0x7F
    if not 1 <= size <= 4 or len(data) < size + 2:
        return False
    return int.from_bytes(data[2 : 2 + size], "big") + size + 2 == len(data)


def _base64_der(value):
    compact = re.sub(r"[\s\"']", "", value)
    if len(compact) < 16:
        return False
    compact += "=" * (-len(compact) % 4)
    try:
        decoded = base64.b64decode(compact, validate=True)
    except ValueError:
        return False
    return _valid_der_sequence(decoded)


def _ipv4_policy(value):
    address = ipaddress.IPv4Address(value)
    if address == ipaddress.IPv4Address("0.0.0.0"):
        return "unspecified"
    if address == ipaddress.IPv4Address("255.255.255.255"):
        return "broadcast"
    networks = (
        ("private-10", "10.0.0.0/8"),
        ("carrier-grade", "100.64.0.0/10"),
        ("loopback", "127.0.0.0/8"),
        ("link-local", "169.254.0.0/16"),
        ("private-172", "172.16.0.0/12"),
        ("private-192", "192.168.0.0/16"),
        ("benchmark", "198.18.0.0/15"),
        ("multicast-documentation", "233.252.0.0/24"),
    )
    return next((name for name, network in networks if address in ipaddress.IPv4Network(network)), "outside")


def _allowed_ipv4(value):
    return _ipv4_policy(value) != "outside"


def _ipv6_policy(value):
    address = ipaddress.IPv6Address(value)
    if address == ipaddress.IPv6Address("::"):
        return "unspecified"
    if address == ipaddress.IPv6Address("::1"):
        return "loopback"
    networks = (
        ("documentation", "2001:db8::/32"),
        ("ula", "fd00::/8"),
        ("link-local", "fe80::/10"),
        ("site-local", "fec0::/10"),
        ("multicast", "ff00::/8"),
    )
    return next((name for name, network in networks if address in ipaddress.IPv6Network(network)), "outside")


def _allowed_ipv6(value):
    return _ipv6_policy(value) != "outside"


def _allowed_ipv4_fragment(parts):
    return anonymize.mapped_ipv4_fragment(parts)


def _ipv4_fragment_policy(parts):
    if not _allowed_ipv4_fragment(parts):
        return "outside"
    category = anonymize.Mapper._ip4_category(parts)
    return "benchmark" if category == "public" else "multicast-documentation" if category == "multicast" else category


def _host_is_opaque(value):
    labels = value.rstrip(".").split(".")
    for label in labels:
        body = label.removeprefix("_")
        if re.fullmatch(r"[0-9a-f]{16,}", body, re.IGNORECASE):
            return True
    return False


def _first_alnum(value):
    return next((char for char in value if char.isalnum()), "")


def _synthetic_word(value):
    return bool(re.fullmatch(r"q(?:[aeiou][bcdfghjklmnprstvwz])*(?:[aeiou])?", value))


def _synthetic_token(value):
    words = re.findall(r"[A-Za-z0-9]+", value)
    return bool(words) and all(_synthetic_word(word) or word.startswith("Q") or word.lower() in anonymize.TXT_WORDS or word.lower() in anonymize.KEEP_LABELS for word in words)


def _source_host_is_sensitive(value):
    labels = value.rstrip(".").split(".")
    for label in labels:
        lower = label.lower()
        if label in {"", "*", "@"} or lower in anonymize.KEEP_LABELS or lower in anonymize.KEEP_UNDERSCORE_LABELS:
            continue
        return True
    return False


def _source_candidates(table, column, value, record_type=""):
    if not value or table in STATIC_ROWS or value in ROW_STRING_LITERALS.get((table, column), set()) or anonymize.SAFE_LITERAL.fullmatch(value):
        return set()
    field = (table, column)
    txt_field = table in {"nt_zone_record", "nt_zone_record_log"} and column == "address" and record_type in TXT_TYPES
    record_other = table in {"nt_zone_record", "nt_zone_record_log"} and column == "other" and not re.fullmatch(r"[\d\s]*", value)
    host_field = field in HOST_FIELDS or (table in {"nt_zone_record", "nt_zone_record_log"} and column == "address" and record_type in HOST_TYPES)
    mapped_field = field in PERSONAL_FIELDS or field in WORDS_FIELDS or host_field or txt_field or record_other or table in DROP_ROWS
    if not mapped_field:
        return set()
    candidates = set()

    def add(category, candidate, global_check=False):
        normalized = _normalized(candidate)
        if normalized:
            candidates.add((category, candidate, global_check))

    if field in PERSONAL_FIELDS and value.casefold() not in {"nictool", "root", "nictest"}:
        add("personal", value, len(value) >= 4 and value.casefold() not in SOURCE_PUBLIC_LITERALS)
    if host_field and _source_host_is_sensitive(value):
        add("host", value, len(value) >= 4)
    remaining = value
    for email in anonymize.Mapper.EMAIL_RE.findall(value):
        add("email", email, True)
    remaining = anonymize.Mapper.EMAIL_RE.sub(" ", remaining)
    for match in anonymize.Mapper.IP6_RE.finditer(remaining):
        try:
            address = ipaddress.IPv6Address(match.group(0))
        except ValueError:
            continue
        if address not in {ipaddress.IPv6Address("::"), ipaddress.IPv6Address("::1")}:
            add("ipv6", match.group(0), True)
    remaining = anonymize.Mapper.IP6_RE.sub(" ", remaining)
    for candidate in anonymize.Mapper.IP4_RE.findall(remaining):
        try:
            address = ipaddress.IPv4Address(candidate) if len(candidate.split(".")) == 4 else None
        except ValueError:
            continue
        if address not in {ipaddress.IPv4Address("0.0.0.0"), ipaddress.IPv4Address("127.0.0.1"), ipaddress.IPv4Address("255.255.255.255")}:
            add("ipv4", candidate, len(candidate) >= 4)
    remaining = anonymize.Mapper.IP4_RE.sub(" ", remaining)
    for host in anonymize.Mapper.HOST_RE.findall(remaining):
        if _source_host_is_sensitive(host):
            add("host", host, len(host) >= 4)
    remaining = anonymize.Mapper.HOST_RE.sub(" ", remaining)
    if txt_field:
        if not re.search(r"\bv\s*=\s*DMARC1\b", value, re.IGNORECASE):
            for key in anonymize.Mapper.DKIM_RE.finditer(remaining):
                add("dkim", key.group(2), True)
            remaining = anonymize.Mapper.DKIM_RE.sub(" ", remaining)
        for verification in anonymize.Mapper.VERIFICATION_RE.finditer(remaining):
            add("verification", verification.group(3), True)
        remaining = anonymize.Mapper.VERIFICATION_RE.sub(" ", remaining)
        for verification in re.finditer(r"\bMS\s*=\s*ms(\d+)\b", remaining, re.IGNORECASE):
            add("verification", verification.group(1), len(verification.group(1)) >= 4)
        remaining = re.sub(r"\bMS\s*=\s*ms\d+\b", " ", remaining, flags=re.IGNORECASE)
    for token in anonymize.Mapper.TOKEN_RE.findall(remaining):
        words = re.findall(r"[A-Za-z0-9]+", token)
        if token.lower() not in VERIFICATION_KEYS and not all(word.lower() in SOURCE_PROTOCOL_WORDS for word in words):
            add("token", token, len(token) >= 8)
    remaining = anonymize.Mapper.TOKEN_RE.sub(" ", remaining)
    if field in WORDS_FIELDS or txt_field or record_other:
        for word in anonymize.Mapper.WORD_RE.findall(remaining):
            components = re.findall(r"[^\W_]+", word, re.UNICODE)
            if word.lower() not in SOURCE_PROTOCOL_WORDS and (not components or not all(component.lower() in SOURCE_PROTOCOL_WORDS for component in components)):
                add("word", word)
        for digits in re.findall(r"\d{4,}", remaining):
            add("digits", digits)
    return candidates


def _source_value_parts(value):
    parts = {category: set() for category in ("digits", "dkim", "email", "host", "ipv4", "ipv6", "token", "verification", "word")}
    remaining = value
    parts["email"].update(_normalized(candidate) for candidate in anonymize.Mapper.EMAIL_RE.findall(remaining))
    remaining = anonymize.Mapper.EMAIL_RE.sub(" ", remaining)
    parts["ipv6"].update(_normalized(match.group(0)) for match in anonymize.Mapper.IP6_RE.finditer(remaining))
    remaining = anonymize.Mapper.IP6_RE.sub(" ", remaining)
    parts["ipv4"].update(_normalized(candidate) for candidate in anonymize.Mapper.IP4_RE.findall(remaining))
    remaining = anonymize.Mapper.IP4_RE.sub(" ", remaining)
    parts["host"].update(_normalized(candidate) for candidate in anonymize.Mapper.HOST_RE.findall(remaining))
    remaining = anonymize.Mapper.HOST_RE.sub(" ", remaining)
    if not re.search(r"\bv\s*=\s*DMARC1\b", remaining, re.IGNORECASE):
        parts["dkim"].update(_normalized(match.group(2)) for match in anonymize.Mapper.DKIM_RE.finditer(remaining))
        remaining = anonymize.Mapper.DKIM_RE.sub(" ", remaining)
    parts["verification"].update(_normalized(match.group(3)) for match in anonymize.Mapper.VERIFICATION_RE.finditer(remaining))
    remaining = anonymize.Mapper.VERIFICATION_RE.sub(" ", remaining)
    parts["verification"].update(_normalized(match.group(1)) for match in re.finditer(r"\bMS\s*=\s*ms(\d+)\b", remaining, re.IGNORECASE))
    remaining = re.sub(r"\bMS\s*=\s*ms\d+\b", " ", remaining, flags=re.IGNORECASE)
    parts["token"].update(_normalized(candidate) for candidate in anonymize.Mapper.TOKEN_RE.findall(remaining))
    remaining = anonymize.Mapper.TOKEN_RE.sub(" ", remaining)
    parts["word"].update(_normalized(candidate) for candidate in anonymize.Mapper.WORD_RE.findall(remaining))
    parts["digits"].update(_normalized(candidate) for candidate in re.findall(r"\d{4,}", remaining))
    parts["personal"] = {_normalized(value)}
    return parts


def _source_candidate_retained(category, candidate, output_value, parts=None):
    normalized = _normalized(candidate)
    if not normalized:
        return False
    parts = parts or _source_value_parts(output_value)
    if category == "host" and normalized == _normalized(output_value):
        return True
    return normalized in parts.get(category, set())


def _compare_source(report, source_text, corpus_text, manifest):
    known_columns = SCHEMA_COLUMNS.get(manifest.get("input_contract", {}).get("db_version"), KNOWN_COLUMNS)
    string_columns = SCHEMA_STRING_COLUMNS.get(manifest.get("input_contract", {}).get("db_version"), STRING_COLUMNS)
    source_items = anonymize.parse_dump(source_text, known_columns=known_columns, string_columns=string_columns)
    corpus_items = anonymize.parse_dump(corpus_text, known_columns=known_columns, string_columns=string_columns)
    source_rows = Counter()
    source_by_table = {}
    corpus_by_table = {}
    for kind, table, payload in source_items:
        if kind == "insert":
            source_rows[table] += len(payload)
            source_by_table.setdefault(table, []).extend(payload)
    for kind, table, payload in corpus_items:
        if kind == "insert":
            corpus_by_table.setdefault(table, []).extend(payload)
    if dict(sorted(source_rows.items())) != manifest.get("source_rows"):
        _failure(report, "manifest_source_row_count_mismatch")
    retention_profile = manifest.get("retention", {}).get("profile")
    if retention_profile not in anonymize.RETENTION_PROFILES:
        retention_profile = "full"
    kept_history, retention_dropped = anonymize.retention_plan(source_items, known_columns, retention_profile)
    if manifest.get("retention") != anonymize.retention_metadata(retention_profile, retention_dropped):
        _failure(report, "source_retention_plan_mismatch")
    global_candidates = {}
    for table, rows in source_by_table.items():
        columns = known_columns[table]
        output_rows = corpus_by_table.get(table, [])
        if table in DROP_ROWS:
            output_rows = [None] * len(rows)
        elif table in kept_history:
            if len(output_rows) != len(kept_history[table]):
                _failure(report, "source_output_row_count_mismatch")
                continue
            retained = iter(output_rows)
            output_rows = [next(retained) if index in kept_history[table] else None for index in range(len(rows))]
        elif len(rows) != len(output_rows):
            _failure(report, "source_output_row_count_mismatch")
            continue
        for row, output_row in zip(rows, output_rows):
            record_type = str(row[columns.index("type_id")]) if "type_id" in columns else ""
            for index, (column, source_value) in enumerate(zip(columns, row)):
                if isinstance(source_value, anonymize.Raw):
                    if (table, column) not in string_columns and output_row is not None and source_value != output_row[index]:
                        _failure(report, "source_relational_value_changed")
                        _failure_field(report, f"source_relational:{table}.{column}")
                    continue
                candidates = _source_candidates(table, column, source_value, record_type)
                report["counts"]["source_candidates"] = report["counts"].get("source_candidates", 0) + len(candidates)
                output_value = "" if output_row is None else output_row[index]
                output_text_value = "" if isinstance(output_value, anonymize.Raw) else output_value
                output_parts = _source_value_parts(output_text_value)
                for category, candidate, global_check in candidates:
                    normalized = _normalized(candidate)
                    if _source_candidate_retained(category, candidate, output_text_value, output_parts):
                        _failure(report, "source_value_retained")
                        key = f"source_same_field:{table}.{column}:{category}"
                        _failure_field(report, key)
                    if global_check and normalized:
                        global_candidates.setdefault(category, set()).add(normalized)
    corpus_parts = {key: set() for key in ("dkim", "email", "host", "ipv4", "ipv6", "personal", "token", "verification", "word")}
    for rows in corpus_by_table.values():
        for row in rows:
            for value in row:
                if not isinstance(value, str) or isinstance(value, anonymize.Raw):
                    continue
                parts = _source_value_parts(value)
                for category, candidates in corpus_parts.items():
                    candidates.update(parts.get(category, set()))
                corpus_parts["personal"].update(parts["word"])
    match_count = 0
    indicator_count = 0
    for category, candidates in global_candidates.items():
        indicator_count += len(candidates)
        matches = candidates & corpus_parts.get(category, set())
        match_count += len(matches)
        if matches:
            _failure_field(report, f"source_global:{category}", len(matches))
    if match_count:
        _failure(report, "source_indicator_match", match_count)
    report["counts"]["source_global_indicators"] = indicator_count
    report["counts"]["source_global_matches"] = match_count
    report["source_input"] = "provided"


def _scan_value(report, table, column, value, record_type):
    for email in anonymize.Mapper.EMAIL_RE.findall(value):
        report["counts"]["email_candidates"] += 1
        domain = email.rsplit("@", 1)[1].rstrip(".").lower()
        _classification(report, "email", table, column, "test" if domain.endswith(".test") else "example" if domain.endswith(".example") else "outside")
        if not domain.endswith((".test", ".example")):
            _failure(report, "email_outside_test_domains")

    for candidate in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", value):
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError:
            continue
        report["counts"]["ipv4_candidates"] += 1
        policy = _ipv4_policy(candidate)
        _classification(report, "ipv4", table, column, policy)
        if policy == "outside":
            _failure(report, "ipv4_outside_policy")

    for match in anonymize.Mapper.IP6_RE.finditer(value):
        try:
            ipaddress.IPv6Address(match.group(0))
        except ValueError:
            continue
        report["counts"]["ipv6_candidates"] += 1
        policy = _ipv6_policy(match.group(0))
        _classification(report, "ipv6", table, column, policy)
        if policy == "outside":
            _failure(report, "ipv6_outside_policy")

    if (table, column) in FRAGMENT_FIELDS:
        for candidate in anonymize.Mapper.IP4_RE.findall(value):
            parts = candidate.split(".")
            if len(parts) == 4 or any(int(part) > 255 for part in parts):
                continue
            report["counts"]["ipv4_fragments"] += 1
            policy = _ipv4_fragment_policy(parts)
            _classification(report, "ipv4_fragment", table, column, policy)
            if policy == "outside":
                _failure(report, "ipv4_fragment_outside_policy")

    if (table, column) in HOST_FIELDS or (table in {"nt_zone_record", "nt_zone_record_log"} and column == "address" and record_type in HOST_TYPES):
        report["counts"]["hostname_fields"] += 1
        opaque = _host_is_opaque(value)
        _classification(report, "hostname", table, column, "opaque" if opaque else "mapped-or-allowlisted")
        if opaque:
            _failure(report, "opaque_hex_dns_label")

    if table in {"nt_zone_record", "nt_zone_record_log"} and column == "address" and record_type == "29":
        report["counts"]["loc_values"] += 1
        loc = anonymize.Mapper.LOC_RE.fullmatch(value)
        coordinates = None if not loc else (loc.group(1), loc.group(2), float(loc.group(3)), loc.group(4).upper(), loc.group(5), loc.group(6), float(loc.group(7)), loc.group(8).upper(), float(loc.group(9)))
        if coordinates not in {("51", "30", 0.0, "N", "0", "7", 0.0, "W", 100.0), ("51", "31", 0.0, "N", "0", "7", 0.0, "W", 100.0)}:
            _failure(report, "loc_value_not_synthetic")
        for group, expected in ((11, 1), (13, 10000), (15, 10)):
            if loc and loc.group(group) is not None and float(loc.group(group)) != expected:
                _failure(report, "loc_value_not_synthetic")
                break

    if table in {"nt_zone_record", "nt_zone_record_log"} and column == "address" and record_type in TXT_TYPES:
        report["counts"]["txt_values"] += 1
        _classification(report, "txt", table, column, f"rr-{record_type}")
        microsoft_pattern = re.compile(r"\bMS\s*=\s*ms(\d+)\b", re.IGNORECASE)
        for verification in microsoft_pattern.finditer(value):
            report["counts"]["microsoft_verification_values"] += 1
            _classification(report, "verification", table, column, "microsoft")
            if not verification.group(1).startswith("0"):
                _failure(report, "microsoft_verification_not_marked_synthetic")
        dkim_pattern = anonymize.Mapper.DKIM_RE
        dkim_matches = () if re.search(r"\bv\s*=\s*DMARC1\b", value, re.IGNORECASE) else dkim_pattern.finditer(value)
        for key in dkim_matches:
            report["counts"]["dkim_keys"] += 1
            _classification(report, "key_material", table, column, "dkim")
            material = key.group(2)
            if _first_alnum(material) != "Q":
                _failure(report, "dkim_key_not_marked_synthetic")
            if _base64_der(material):
                _failure(report, "plausible_complete_der_key")
        scrubbed = value if re.search(r"\bv\s*=\s*DMARC1\b", value, re.IGNORECASE) else dkim_pattern.sub(" ", value)
        for verification in anonymize.Mapper.VERIFICATION_RE.finditer(scrubbed):
            report["counts"]["provider_verification_values"] += 1
            _classification(report, "verification", table, column, "provider")
            if _first_alnum(verification.group(3)) != "Q":
                _failure(report, "provider_verification_not_marked_synthetic")
        scrubbed = anonymize.Mapper.VERIFICATION_RE.sub(" ", microsoft_pattern.sub(" ", scrubbed))
        scrubbed = anonymize.Mapper.EMAIL_RE.sub(" ", scrubbed)
        scrubbed = anonymize.Mapper.HOST_RE.sub(" ", scrubbed)
        scrubbed = anonymize.Mapper.IP4_RE.sub(" ", scrubbed)
        scrubbed = anonymize.Mapper.IP6_RE.sub(" ", scrubbed)
        for token in anonymize.Mapper.TOKEN_RE.findall(scrubbed):
            if token.lower() in VERIFICATION_KEYS:
                continue
            report["counts"]["opaque_tokens"] += 1
            _classification(report, "opaque_token", table, column, f"rr-{record_type}")
            if _first_alnum(token) != "Q" and not _synthetic_token(token):
                _failure(report, "opaque_token_not_marked_synthetic")
                shape = re.sub(r"[A-Za-z0-9]+", "A", token)
                key = f"{table}.{column}:rr={record_type}:length={len(token)}:shape={shape}"
                report.setdefault("failure_fields", Counter())[key] += 1


def audit_sql(text, manifest, indicators=(), require_indicators=False):
    report = {
        "status": "PASS",
        "counts": Counter(),
        "failures": {},
        "rows": {},
        "indicator_file": "provided" if indicators else "not provided",
    }
    if require_indicators and not indicators:
        _failure(report, "known_indicator_file_required")

    direct_checks = {
        "definer_clause": r"\bDEFINER\s*=",
        "routine_or_trigger": r"\bCREATE\s+(?:PROCEDURE|FUNCTION|TRIGGER|EVENT)\b",
        "dump_host_header": r"(?m)^--\s+(?:Host|Server version):",
        "sql_comment": r"(?m)^\s*(?:--(?:\s|$)|#|/\*)",
    }
    for name, pattern in direct_checks.items():
        count = len(re.findall(pattern, text, re.IGNORECASE))
        report["counts"][name] = count
        if count:
            _failure(report, name, count)

    db_version = manifest.get("input_contract", {}).get("db_version")
    known_columns = SCHEMA_COLUMNS.get(db_version)
    string_columns = SCHEMA_STRING_COLUMNS.get(db_version)
    static_profile = manifest.get("static_lookup_profile")
    static_rows = STATIC_PROFILES.get(static_profile)
    if known_columns is None:
        _failure(report, "manifest_db_version")
        known_columns = KNOWN_COLUMNS
        string_columns = STRING_COLUMNS
        static_rows = STATIC_ROWS
    elif static_rows is None or STATIC_PROFILE_VERSIONS.get(static_profile) != db_version:
        _failure(report, "manifest_static_lookup_profile")
        static_rows = STATIC_ROWS
    try:
        items = anonymize.parse_dump(text, known_columns=known_columns, string_columns=string_columns)
    except anonymize.InputError:
        _failure(report, "sql_contract_error")
        items = []

    sql_text = text
    decoded_values = []
    for kind, _, payload in items:
        if kind != "insert":
            continue
        decoded_values.extend(value for row in payload for value in row if isinstance(value, str) and not isinstance(value, anonymize.Raw))
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    sql_matches = _matched_indicators(indicators, (sql_text, *decoded_values))
    manifest_matches = _matched_indicators(indicators, (manifest_text,))
    report["counts"]["known_indicator_sql"] = len(sql_matches)
    report["counts"]["known_indicator_manifest"] = len(manifest_matches)
    report["counts"]["known_indicators"] = len(sql_matches | manifest_matches)
    if report["counts"]["known_indicators"]:
        _failure(report, "known_indicator_match", report["counts"]["known_indicators"])

    if manifest.get("format") != 2:
        _failure(report, "manifest_format")
    if manifest.get("license") != anonymize.LICENSE:
        _failure(report, "manifest_license")
    if manifest.get("copyright") != anonymize.COPYRIGHT:
        _failure(report, "manifest_copyright")
    if manifest.get("tool") != {"name": "anonymize.py", "version": anonymize.VERSION}:
        _failure(report, "manifest_tool")
    contributor = manifest.get("provenance", {}).get("contributor")
    if not isinstance(contributor, str) or not anonymize.CONTRIBUTOR_RE.fullmatch(contributor):
        _failure(report, "manifest_contributor")
    source_alias = manifest.get("provenance", {}).get("source_alias")
    if not isinstance(source_alias, str) or not anonymize.CONTRIBUTOR_RE.fullmatch(source_alias):
        _failure(report, "manifest_source_alias")
    source_date = manifest.get("provenance", {}).get("source_date")
    if not isinstance(source_date, str) or not anonymize.SOURCE_DATE_RE.fullmatch(source_date):
        _failure(report, "manifest_source_date")
    if manifest.get("provenance", {}).get("raw_source") != "not retained":
        _failure(report, "manifest_raw_source")
    dropped = manifest.get("dropped", {})
    if dropped.get("tables") != sorted(DROP_ROWS) or dropped.get("reason") != "session material":
        _failure(report, "manifest_dropped_tables")
    source_manifest_rows = manifest.get("source_rows")
    output_manifest_rows = manifest.get("rows")
    if not isinstance(source_manifest_rows, dict) or not isinstance(output_manifest_rows, dict):
        _failure(report, "manifest_source_rows")
    else:
        session_rows = {table: source_manifest_rows[table] for table in sorted(DROP_ROWS) if source_manifest_rows.get(table)}
        if dropped.get("rows") != session_rows:
            _failure(report, "manifest_dropped_rows")
        retention_rows = {}
        for table, source_count in source_manifest_rows.items():
            output_count = output_manifest_rows.get(table, 0)
            if output_count > source_count:
                _failure(report, "manifest_output_exceeds_source_rows")
            elif table not in DROP_ROWS and output_count < source_count:
                retention_rows[table] = source_count - output_count
        retention = manifest.get("retention", {})
        retention_profile = retention.get("profile")
        if retention_profile not in anonymize.RETENTION_PROFILES:
            _failure(report, "manifest_retention_profile")
        elif retention != anonymize.retention_metadata(retention_profile, retention_rows):
            _failure(report, "manifest_retention")

    rows = Counter()
    for kind, table, payload in items:
        if kind != "insert":
            continue
        rows[table] += len(payload)
        columns = known_columns[table]
        for row in payload:
            values = dict(zip(columns, row))
            record_type = str(values.get("type_id", ""))
            if table in static_rows and tuple(str(value) for value in row) not in static_rows[table]:
                _failure(report, "static_lookup_outside_allowlist")
            if table in DROP_ROWS:
                _failure(report, "session_row", len(payload))
                break
            if table == "nt_user":
                password = values["password"]
                salt = values["pass_salt"]
                if not isinstance(password, str) or isinstance(password, anonymize.Raw) or not re.fullmatch(r"[0-9a-f]{64}", password):
                    _failure(report, "password_hash_format")
                if not isinstance(salt, str) or isinstance(salt, anonymize.Raw) or not re.fullmatch(r"[A-Za-z0-9+/]{16}", salt):
                    _failure(report, "password_salt_format")
            for column, value in values.items():
                if isinstance(value, anonymize.Raw):
                    continue
                _scan_value(report, table, column, value, record_type)

    report["rows"] = dict(sorted(rows.items()))
    expected_rows = manifest.get("rows")
    if expected_rows != report["rows"]:
        _failure(report, "manifest_row_count_mismatch")
    if report["failures"]:
        report["status"] = "FAIL"
    report["counts"] = dict(sorted(report["counts"].items()))
    if "classifications" in report:
        report["classifications"] = {category: dict(sorted(values.items())) for category, values in sorted(report["classifications"].items())}
    if "failure_fields" in report:
        report["failure_fields"] = dict(sorted(report["failure_fields"].items()))
    return report


def read_indicators(path):
    if not path:
        return []
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        raise anonymize.InputError("indicator file must not be group or world accessible")
    with open(path, "r", encoding="utf8") as stream:
        return [line.rstrip("\n") for line in stream if line.rstrip("\n")]


def audit_paths(corpus_path, manifest_path, indicator_path=None, require_indicators=False, source_path=None, require_source=False):
    with open(corpus_path, "rb") as stream:
        corpus_bytes = stream.read()
    if corpus_path.endswith(".gz"):
        text = gzip.decompress(corpus_bytes).decode("utf8")
    else:
        text = corpus_bytes.decode("utf8")
    with open(manifest_path, "r", encoding="utf8") as stream:
        manifest = json.load(stream)
    report = audit_sql(text, manifest, read_indicators(indicator_path), require_indicators)
    if source_path:
        if stat.S_IMODE(os.stat(source_path).st_mode) & 0o077:
            raise anonymize.InputError("source dump must be mode 0600")
        opener = gzip.open if source_path.endswith(".gz") else open
        with opener(source_path, "rt", encoding="utf8", newline="") as stream:
            source_text = stream.read()
        source_bytes = source_text.encode()
        expected_source = manifest.get("source", {})
        if expected_source.get("sha256") != hashlib.sha256(source_bytes).hexdigest():
            _failure(report, "manifest_source_sha256_mismatch")
        if expected_source.get("bytes") != len(source_bytes):
            _failure(report, "manifest_source_bytes_mismatch")
        _compare_source(report, source_text, text, manifest)
    else:
        report["source_input"] = "not provided"
        if require_source:
            _failure(report, "source_file_required")
    expected = manifest.get("corpus", {})
    compressed = corpus_path.endswith(".gz")
    if expected.get("compressed") is None:
        _failure(report, "manifest_compressed_missing")
    elif expected.get("compressed") is not compressed:
        _failure(report, "manifest_compressed_mismatch")
    checks = {
        "corpus_sha256": (expected.get("sha256"), hashlib.sha256(corpus_bytes).hexdigest()),
        "sql_sha256": (expected.get("sql_sha256"), hashlib.sha256(text.encode()).hexdigest()),
        "corpus_bytes": (expected.get("bytes"), len(corpus_bytes)),
        "sql_bytes": (expected.get("sql_bytes"), len(text.encode())),
    }
    for name, (wanted, actual) in checks.items():
        if wanted is None:
            _failure(report, f"manifest_{name}_missing")
        elif wanted != actual:
            _failure(report, f"manifest_{name}_mismatch")
    if report["failures"]:
        report["status"] = "FAIL"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus")
    parser.add_argument("manifest")
    parser.add_argument("--indicators", help="mode-0600 file with one literal known indicator per line")
    parser.add_argument("--require-indicators", action="store_true")
    parser.add_argument("--source", help="mode-0600 raw source dump for private source comparison")
    parser.add_argument("--require-source", action="store_true")
    parser.add_argument("--output", help="write the JSON report with mode 0600")
    arguments = parser.parse_args(argv)
    try:
        report = audit_paths(arguments.corpus, arguments.manifest, arguments.indicators, arguments.require_indicators, arguments.source, arguments.require_source)
        encoded = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        if arguments.output:
            anonymize._write_atomic(arguments.output, encoded)
        else:
            print(encoded.decode(), end="")
    except (anonymize.InputError, OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.exit(1, f"audit.py: {error}\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
