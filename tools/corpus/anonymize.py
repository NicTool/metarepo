#!/usr/bin/env python3
# Copyright (c) 2026, The NicTool Contributors

"""Turn a supported NicTool mysqldump into a deterministic test corpus."""

import argparse
import base64
import gzip
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import stat
import tempfile
from collections import Counter

from schema import (
    DDL_STRING_LITERALS,
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
    TRUNCATABLE_FIELDS,
    TXT_TYPES,
)

VERSION = "0.7.0"
PASSWORD = "nictool-corpus"
LICENSE = "BSD-3-Clause"
COPYRIGHT = "Copyright (c) 2026, The NicTool Contributors"
CONTRIBUTOR_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,38}[a-z0-9])?")
SOURCE_DATE_RE = re.compile(r"(?:undated|\d{4}-\d{2}-\d{2})")


class InputError(ValueError):
    pass


class Oracle:
    def __init__(self, secret):
        self.secret = secret.encode()

    def bytes(self, kind, value, size=32):
        out = b""
        counter = 0
        while len(out) < size:
            message = f"{kind}\0{value}\0{counter}".encode()
            out += hmac.new(self.secret, message, hashlib.sha256).digest()
            counter += 1
        return out[:size]

    def integer(self, kind, value, low, high):
        number = int.from_bytes(self.bytes(kind, value, 8), "big")
        return low + number % (high - low + 1)

    def pick(self, kind, value, choices):
        return choices[self.integer(kind, value, 0, len(choices) - 1)]


CONSONANTS = "bcdfghjklmnprstvwz"
VOWELS = "aeiou"
FIRST = ("alex", "sam", "jordan", "taylor", "casey", "morgan", "riley", "avery", "quinn", "drew", "jamie", "robin", "kai", "noor", "tariq", "mina", "ines", "luca", "sana", "ravi", "ola", "femi", "yara", "ivo")
LAST = ("reyes", "okafor", "lindqvist", "nakamura", "haddad", "moreau", "petrov", "ashworth", "delgado", "kowalski", "brennan", "mehta", "sato", "oduya", "varga", "castellano", "nyberg", "farah", "quintero", "hale")
KEEP_LABELS = {"www", "mail", "ns", "ns1", "ns2", "ns3", "mx", "mx1", "mx2", "smtp", "imap", "pop", "pop3", "ftp", "webmail", "hostmaster", "postmaster", "localhost", "default", "dkim", "selector1", "selector2", "autodiscover", "autoconfig", "api", "app", "dev", "test", "staging", "vpn", "git"}
KEEP_UNDERSCORE_LABELS = {"_acme-challenge", "_domainkey", "_dmarc", "_tcp", "_udp"}
FAKE_TLDS = ("test", "example")
SAFE_IP4 = {ipaddress.IPv4Address("127.0.0.1")}
SAFE_IP6 = {ipaddress.IPv6Address("::"), ipaddress.IPv6Address("::1")}
TXT_WORDS = {"a", "adkim", "all", "aspf", "dkim1", "dmarc1", "ed25519", "email", "exists", "fo", "h", "include", "ip4", "ip6", "k", "mailto", "mx", "none", "p", "pct", "ptr", "quarantine", "reject", "relaxed", "redirect", "rsa", "rua", "ruf", "s", "sha1", "sha256", "spf1", "strict", "t", "v"}


def valid_ipv4_parts(parts):
    return all(re.fullmatch(r"(?:0|[1-9][0-9]{0,2})", part) and int(part) <= 255 for part in parts)


def mapped_ipv4_fragment(parts):
    if not 2 <= len(parts) <= 4 or not valid_ipv4_parts(parts):
        return False
    first, second = int(parts[0]), int(parts[1])
    return (
        parts in (["0", "0", "0", "0"], ["255", "255", "255", "255"])
        or first == 10
        or first == 127
        or (first == 100 and 64 <= second <= 127)
        or (first == 169 and second == 254)
        or (first == 172 and 16 <= second <= 31)
        or (first == 192 and second == 168)
        or (first == 198 and second in {18, 19})
        or (first == 233 and second == 252)
    )


class Mapper:
    EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
    IP4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){1,3}\d{1,3}(?![\d.])")
    IP6_RE = re.compile(r"(?<![\w:.])(?=[0-9a-f:]*:)[0-9a-f:]+(?![\w:.])", re.IGNORECASE)
    HOST_RE = re.compile(r"(?<![\w.-])(?:\*\.)?(?=[a-z0-9_.*-]*[a-z_])[a-z0-9_*-]+(?:\.[a-z0-9_*-]+)+\.?(?![\w.-])", re.IGNORECASE)
    WORD_RE = re.compile(r"[^\W\d_](?:[^\W_]|[-'][^\W_])*", re.UNICODE)
    DKIM_RE = re.compile(r"(\bp\s*=\s*)((?:[\"']?[a-z0-9+/=]+[\"']?)(?:\s+[\"']?[a-z0-9+/=]+[\"']?)*)", re.IGNORECASE)
    VERIFICATION_RE = re.compile(
        r"\b((?:google|facebook|apple|atlassian)-domain-verification|google-site-verification|keybase-site-verification)\s*([=:])\s*([^;\s\"]+)",
        re.IGNORECASE,
    )
    TOKEN_RE = re.compile(r"(?<![\w+/=_.:-])(?:[a-z0-9]{3,}[+/=_.:-])+(?:[a-z0-9]{3,})|(?<![\w+/=_-])[a-z0-9+/=_-]{12,}(?![\w+/=_-])", re.IGNORECASE)
    LOC_RE = re.compile(
        r"\s*(\d{1,2})\s+(\d{1,2})\s+(\d+(?:\.\d+)?)\s+([NS])\s+"
        r"(\d{1,3})\s+(\d{1,2})\s+(\d+(?:\.\d+)?)\s+([EW])\s+"
        r"(-?\d+(?:\.\d+)?)(m)?"
        r"(?:\s+(\d+(?:\.\d+)?)(m)?)?"
        r"(?:\s+(\d+(?:\.\d+)?)(m)?)?"
        r"(?:\s+(\d+(?:\.\d+)?)(m)?)?\s*",
        re.IGNORECASE,
    )

    def __init__(self, secret, reserved=()):
        self.oracle = Oracle(secret)
        self.reserved = {value.casefold() for value in reserved if value}
        self.seen = Counter()
        self.labels = {}
        self.label_owners = {}
        self.usernames = {}
        self.username_owners = {}
        self.zones = {}

    def label(self, value):
        low = value.lower()
        if not value or low in KEEP_LABELS or value in {"*", "@"}:
            return value
        if low in KEEP_UNDERSCORE_LABELS:
            return value
        prefix = "_" if value.startswith("_") else ""
        body = value[1:] if prefix else value
        if not body:
            return value
        key = body.casefold()
        if key in self.labels:
            self.seen["labels"] += 1
            return prefix + self.labels[key]
        mapped = None
        for attempt in range(256):
            out = ["q"]
            for index in range(1, max(8, len(body))):
                choices = VOWELS if index % 2 else CONSONANTS
                seed = f"{body.casefold()}:{index}" if attempt == 0 else f"{body.casefold()}:{attempt}:{index}"
                out.append(self.oracle.pick("label", seed, choices))
            candidate = "".join(out)
            if len(candidate) == 1 and (candidate.casefold() == body.casefold() or candidate.casefold() in self.reserved):
                candidate += self.oracle.pick("label-short", f"{body.casefold()}:{attempt}", VOWELS)
            if candidate.casefold() != body.casefold() and candidate.casefold() not in self.reserved and candidate not in self.label_owners:
                mapped = candidate
                break
        if mapped is None:
            raise InputError("could not generate a non-reserved DNS label")
        self.seen["labels"] += 1
        self.labels[key] = mapped
        self.label_owners[mapped] = key
        return prefix + mapped

    def host(self, name):
        if not name:
            return name
        trailing_dot = name.endswith(".")
        raw = name[:-1] if trailing_dot else name
        labels = raw.split(".")
        lowered = [label.lower() for label in labels]
        if len(labels) >= 2 and lowered[-1] == "arpa" and lowered[-2] in {"in-addr", "ip6"}:
            mapped = self.reverse(labels)
        else:
            mapped_prefix = []
            leading_ip = re.match(r"^(\d{1,3}(?:\.\d{1,3}){1,3})(\..+)$", raw)
            if leading_ip:
                parts = leading_ip.group(1).split(".")
                if all(int(part) <= 255 for part in parts):
                    mapped_prefix = self.ip4_prefix(leading_ip.group(1), len(parts)).split(".")
                    labels = leading_ip.group(2)[1:].split(".")
                    lowered = [label.lower() for label in labels]
            mapped = mapped_prefix + [self.label(label) for label in labels]
            mapped.append(self.oracle.pick("tld", lowered[-1], FAKE_TLDS))
        self.seen["hosts"] += 1
        return ".".join(mapped) + ("." if trailing_dot else "")

    def record_host(self, value, zone):
        # NicTool qualifies a name by appending its zone unless it ends in a dot or already ends with the zone.
        if not value or value in {"@", "*"}:
            return value
        if value.endswith(".") or not zone:
            return self.host(value) if "." in value or value.endswith(".") else self.label(value)
        zone = zone.rstrip(".")
        if value.lower().endswith(zone.lower()):
            return self.host(value)
        mapped_zone = self.host(zone + ".")
        mapped = self.host(f"{value}.{zone}.")
        if mapped.endswith("." + mapped_zone):
            return mapped[: -len(mapped_zone) - 1]
        return ".".join(self.label(label) for label in value.split("."))

    def reverse(self, labels):
        if labels[-2].lower() == "in-addr":
            octets = labels[:-2]
            if all(part.isdigit() and int(part) <= 255 for part in octets):
                prefix = ".".join(reversed(octets))
                mapped = self.ip4_prefix(prefix, len(octets))
                return list(reversed(mapped.split("."))) + labels[-2:]
        else:
            nibbles = labels[:-2]
            if nibbles and all(re.fullmatch(r"[0-9a-f]", part, re.IGNORECASE) for part in nibbles):
                source = "".join(reversed(nibbles)).lower()
                if len(source) == 32:
                    address = ipaddress.IPv6Address(int(source, 16))
                    mapped = ipaddress.IPv6Address(self.ip6(str(address))).exploded.replace(":", "")
                else:
                    size = max(1, (len(source) + 1) // 2)
                    tail = self.oracle.bytes("ip6-prefix", source, size).hex()
                    prefix = "20010db8"
                    if source.startswith(("fc", "fd")):
                        prefix = "fd"
                    elif len(source) >= 3 and 0xFE8 <= int(source[:3], 16) <= 0xFEB:
                        prefix = "fe8"
                    elif len(source) >= 3 and 0xFEC <= int(source[:3], 16) <= 0xFEF:
                        prefix = "fec"
                    elif source.startswith("ff"):
                        prefix = source[: min(4, len(source))]
                    mapped = (prefix + tail)[:len(source)]
                    if mapped == source:
                        mapped = mapped[:-1] + format((int(mapped[-1], 16) + 1) % 16, "x")
                return list(reversed(mapped)) + labels[-2:]
        return [self.label(label) for label in labels[:-2]] + labels[-2:]

    def ip4_prefix(self, prefix, count):
        parts = prefix.split(".")
        if not 1 <= count <= 4 or len(parts) != count or not all(part.isdigit() and int(part) <= 255 for part in parts):
            return prefix
        if count == 4:
            return self.ip4(prefix)
        category = self._ip4_category(parts)
        if category == "private-10":
            mapped = ["10"]
        elif category == "private-172":
            mapped = ["172"]
        elif category == "private-192":
            mapped = ["192", "168"]
        elif category == "link-local":
            mapped = ["169", "254"]
        elif category == "loopback":
            mapped = ["127"]
        elif category == "carrier-grade":
            mapped = ["100"]
        elif category == "multicast":
            mapped = ["233", "252", "0"]
        else:
            mapped = ["198"]
        while len(mapped) < count:
            position = len(mapped)
            source = ".".join(parts[: position + 1])
            if category == "private-172" and position == 1:
                kind, low, high = "ip4/private-172", 16, 31
            elif category == "carrier-grade" and position == 1:
                kind, low, high = "ip4/carrier-grade", 64, 127
            elif category == "public" and position == 1:
                kind, low, high = "ip4/public", 18, 19
            else:
                kind, low, high = f"ip4/{category}/{position}", 0, 255
            value = self.oracle.integer(kind, source, low, high)
            if value == int(parts[position]):
                value = low + (value - low + 1) % (high - low + 1)
            mapped.append(str(value))
        return ".".join(mapped[:count])

    @staticmethod
    def _ip4_category(parts):
        first = int(parts[0])
        second = int(parts[1]) if len(parts) > 1 else None
        if first == 10:
            return "private-10"
        if first == 172 and second is not None and 16 <= second <= 31:
            return "private-172"
        if first == 192 and second == 168:
            return "private-192"
        if first == 169 and second == 254:
            return "link-local"
        if first == 127:
            return "loopback"
        if first == 100 and second is not None and 64 <= second <= 127:
            return "carrier-grade"
        if 224 <= first <= 239:
            return "multicast"
        return "public"

    def ip4(self, value):
        try:
            address = ipaddress.IPv4Address(value)
        except ValueError:
            return value
        if address in SAFE_IP4 or address.is_unspecified or address == ipaddress.IPv4Address("255.255.255.255"):
            return value
        self.seen["ip4"] += 1
        prefix = self.ip4_prefix(value.rsplit(".", 1)[0], 3)
        category = self._ip4_category(value.split("."))
        host = self.oracle.integer(f"ip4/{category}/3", str(address), 0, 255)
        if host == int(value.rsplit(".", 1)[1]):
            host = (host + 1) % 256
        return f"{prefix}.{host}"

    def ip4_field(self, value):
        if not value:
            return value
        parts = value.split(".")
        if not 2 <= len(parts) <= 4 or not valid_ipv4_parts(parts):
            raise InputError("unsupported IPv4 field value")
        return self.ip4_prefix(value, len(parts))

    def ip6(self, value):
        try:
            address = ipaddress.IPv6Address(value)
        except ValueError:
            return value
        if address in SAFE_IP6:
            return value
        if address.ipv4_mapped:
            return "::ffff:" + self.ip4(str(address.ipv4_mapped))
        if address.is_link_local:
            network = ipaddress.IPv6Network("fe80::/10")
            category = "link-local"
        elif address in ipaddress.IPv6Network("fc00::/7"):
            network = ipaddress.IPv6Network("fd00::/8")
            category = "ula"
        elif address in ipaddress.IPv6Network("fec0::/10"):
            network = ipaddress.IPv6Network("fec0::/10")
            category = "site-local"
        elif address.is_multicast:
            network = ipaddress.IPv6Network(f"{address.exploded[:4]}::/16")
            category = "multicast"
        else:
            network = ipaddress.IPv6Network("2001:db8::/32")
            category = "global"
        host_bits = 128 - network.prefixlen
        random = int.from_bytes(self.oracle.bytes(f"ip6/{category}", address.exploded, 16), "big")
        host_mask = (1 << host_bits) - 1
        mapped = ipaddress.IPv6Address(int(network.network_address) | (random & host_mask))
        if mapped == address:
            mapped = ipaddress.IPv6Address(int(network.network_address) | ((int(mapped) + 1) & host_mask))
        self.seen["ip6"] += 1
        return mapped.compressed

    def ip6_field(self, value):
        if not value:
            return value
        try:
            ipaddress.IPv6Address(value)
        except ValueError as error:
            raise InputError("unsupported IPv6 field value") from error
        return self.ip6(value)

    def first(self, value):
        if not value:
            return value
        choices = tuple(name for name in FIRST if name.casefold() != value.casefold() and name.casefold() not in self.reserved)
        return (self.oracle.pick("first", value.casefold(), choices) if choices else self.label(value)).capitalize()

    def last(self, value):
        if not value:
            return value
        choices = tuple(name for name in LAST if name.casefold() != value.casefold() and name.casefold() not in self.reserved)
        return (self.oracle.pick("last", value.casefold(), choices) if choices else self.label(value)).capitalize()

    def username(self, value):
        if not value or value.lower() in {"root", "nictest"}:
            return value
        self.seen["users"] += 1
        choices = tuple(
            first + suffix
            for first in FIRST
            for suffix in ("", "1", "2", "7", "42", "99")
            if (first + suffix).casefold() != value.casefold() and (first + suffix).casefold() not in self.reserved
        )
        key = value.casefold()
        if key in self.usernames:
            return self.usernames[key]
        mapped = None
        for attempt in range(64):
            seed = key if attempt == 0 else f"{key}:{attempt}"
            candidate = self.oracle.pick("username", seed, choices) if choices else self.label(value)
            if attempt >= 8:
                candidate += str(self.oracle.integer("username-suffix", seed, 100, 9999))
            folded = candidate.casefold()
            if folded != key and folded not in self.reserved and folded not in self.username_owners and folded not in {"root", "nictest"}:
                mapped = candidate
                break
        if mapped is None:
            raise InputError("could not generate a distinct username")
        self.usernames[key] = mapped
        self.username_owners[mapped.casefold()] = key
        return mapped

    def email(self, value):
        if not value or "@" not in value:
            return value
        local, domain = value.rsplit("@", 1)
        mapped_domain = self.host(domain)
        if "." not in mapped_domain.rstrip("."):
            mapped_domain = mapped_domain.rstrip(".") + ".test" + ("." if mapped_domain.endswith(".") else "")
        mapped = f"{self.username(local)}@{mapped_domain}"
        if mapped.casefold() == value.casefold():
            mapped = f"{self.label('x' + local)}@{mapped_domain}"
        return mapped

    @staticmethod
    def _slot(index):
        encoded = "".join(chr(0xE100 + int(digit)) for digit in str(index))
        return "\ue000" + encoded + "\ue001"

    @staticmethod
    def _restore(text, saved):
        for index, replacement in enumerate(saved):
            text = text.replace(Mapper._slot(index), replacement)
        return text

    @staticmethod
    def _protect(text, pattern, function, saved):
        def replace(match):
            saved.append(function(match))
            return Mapper._slot(len(saved) - 1)

        return pattern.sub(replace, text)

    def _mapped_fragment(self, match):
        value = match.group(0)
        parts = value.split(".")
        if any(int(part) > 255 for part in parts):
            return value
        return self.ip4(value) if len(parts) == 4 else self.ip4_prefix(value, len(parts))

    def _remap_generated_fragment(self, match):
        return match.group(0) if mapped_ipv4_fragment(match.group(0).split(".")) else self._mapped_fragment(match)

    def _restore_and_scrub_fragments(self, value, saved):
        return self.IP4_RE.sub(self._remap_generated_fragment, self._restore(value, saved))

    def _protect_known(self, value, people, saved):
        value = self._protect(value, self.EMAIL_RE, lambda match: self.email(match.group(0)), saved)
        value = self._protect(value, self.IP6_RE, lambda match: self.ip6(match.group(0)), saved)
        value = self._protect(value, self.IP4_RE, self._mapped_fragment, saved)
        value = self._protect(value, self.HOST_RE, lambda match: self.host(match.group(0)), saved)
        for source, replacement in people:
            if not source:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)", re.IGNORECASE)
            value = self._protect(value, pattern, lambda match, result=replacement: result, saved)
        return value

    def scrub(self, value, people=()):
        if not value:
            return value
        saved = []
        value = self._protect_known(value, people, saved)
        return self._restore_and_scrub_fragments(value, saved)

    def words(self, value, people=()):
        if not value:
            return value
        saved = []
        value = self._protect_known(value, people, saved)
        value = self.WORD_RE.sub(lambda match: self.label(match.group(0)), value)
        value = re.sub(r"\d+", lambda match: self.digits("free-text", match.group(0)), value)
        return self._restore_and_scrub_fragments(value, saved)

    def scrub_value(self, value, people=()):
        return self.words(value, people)

    def _opaque(self, kind, value):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        for attempt in range(256):
            def replace(match, attempt=attempt):
                source = match.group(0)
                chars = ["Q"]
                for offset in range(1, len(source)):
                    seed = f"{value}:{match.start() + offset}" if attempt == 0 else f"{value}:{attempt}:{match.start() + offset}"
                    chars.append(self.oracle.pick(kind, seed, alphabet))
                if len(chars) == 1:
                    chars.append(self.oracle.pick(f"{kind}-short", f"{value}:{attempt}:{match.start()}", alphabet))
                return "".join(chars)

            mapped = re.sub(r"[A-Za-z0-9]+", replace, value)
            runs = re.findall(r"[A-Za-z0-9]+", mapped)
            if mapped != value and all(run.casefold() not in self.reserved for run in runs):
                return mapped
        raise InputError("could not generate non-reserved opaque material")

    def digits(self, kind, value):
        modulus = 10 ** len(value)
        delta = 1 + self.oracle.integer(kind, value, 0, modulus - 2)
        return str((int(value) + delta) % modulus).zfill(len(value))

    def _microsoft(self, match):
        digits = match.group(2)
        if len(digits) == 1:
            if digits == "0":
                raise InputError("one-digit Microsoft verification value cannot be marked safely")
            replacement = "0"
        else:
            replacement = "0" + self.digits("ms", digits[1:])
        return match.group(1) + replacement

    @staticmethod
    def _loc_number(source, number):
        precision = len(source.rsplit(".", 1)[1]) if "." in source else 0
        return f"{number:.{precision}f}"

    def loc(self, value):
        match = self.LOC_RE.fullmatch(value)
        if not match:
            raise InputError("unsupported LOC record value")
        lat_degree, lat_minute, lat_second = int(match.group(1)), int(match.group(2)), float(match.group(3))
        lon_degree, lon_minute, lon_second = int(match.group(5)), int(match.group(6)), float(match.group(7))
        if lat_degree > 90 or lon_degree > 180 or lat_minute > 59 or lon_minute > 59 or not 0 <= lat_second < 60 or not 0 <= lon_second < 60:
            raise InputError("invalid LOC record coordinates")
        if (lat_degree == 90 and (lat_minute or lat_second)) or (lon_degree == 180 and (lon_minute or lon_second)):
            raise InputError("invalid LOC record coordinates")
        lat_seconds = self._loc_number(match.group(3), 0)
        lon_seconds = self._loc_number(match.group(7), 0)
        altitude = self._loc_number(match.group(9), 100) + (match.group(10) or "")
        same_coordinates = (lat_degree, lat_minute, lat_second, match.group(4).upper(), lon_degree, lon_minute, lon_second, match.group(8).upper()) == (51, 30, 0, "N", 0, 7, 0, "W")
        output = ["51", "31" if same_coordinates else "30", lat_seconds, "N", "0", "7", lon_seconds, "W", altitude]
        for source, unit, number in ((match.group(11), match.group(12), 1), (match.group(13), match.group(14), 10000), (match.group(15), match.group(16), 10)):
            if source is not None:
                output.append(self._loc_number(source, number) + (unit or ""))
        self.seen["loc"] += 1
        return " ".join(output)

    def txt(self, value, people=()):
        if not value:
            return value
        saved = []
        if not re.search(r"\bv\s*=\s*DMARC1\b", value, re.IGNORECASE):
            value = self._protect(value, self.DKIM_RE, lambda match: match.group(1) + self._opaque("dkim", match.group(2)), saved)
        value = self._protect(
            value,
            self.VERIFICATION_RE,
            lambda match: match.group(1) + match.group(2) + self._opaque("verification", match.group(3)),
            saved,
        )
        value = self._protect(
            value,
            re.compile(r"\b(MS\s*=\s*ms)(\d+)\b", re.IGNORECASE),
            self._microsoft,
            saved,
        )
        value = self._protect_known(value, people, saved)
        value = self._protect(value, self.TOKEN_RE, lambda match: self._opaque("token", match.group(0)), saved)
        value = self.WORD_RE.sub(lambda match: match.group(0) if match.group(0).lower() in TXT_WORDS else self.label(match.group(0)), value)
        value = re.sub(r"\d{4,11}", lambda match: self.digits("txt-number", match.group(0)), value)
        return self._restore_and_scrub_fragments(value, saved)


class Raw(str):
    pass


ESCAPES = {"0": "\0", "n": "\n", "r": "\r", "Z": "\x1a", "b": "\b", "t": "\t", "\\": "\\", "'": "'", '"': '"'}
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
RAW_RE = re.compile(rf"(?:NULL|{NUMBER}|0x[0-9a-f]+|b'[01]+'|POINT\(\s*{NUMBER}\s*,\s*{NUMBER}\s*\))", re.IGNORECASE)
STRING_SQL_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext", "enum", "set", "date", "datetime", "timestamp", "time"}
NUMERIC_SQL_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint", "decimal", "numeric", "float", "double", "real", "bit", "bool", "boolean"}
TABLE_OPTIONS_RE = re.compile(
    r"\s*(?:ENGINE\s*=\s*(?:InnoDB|MyISAM)\s*)?"
    r"(?:AUTO_INCREMENT\s*=\s*\d+\s*)?"
    r"(?:(?:DEFAULT\s+)?CHARSET\s*=\s*(?:latin1|utf8|utf8mb3|utf8mb4)\s*)?"
    r"(?:COLLATE\s*=\s*(?:latin1_swedish_ci|utf8_general_ci|utf8mb3_bin|utf8mb3_general_ci|utf8mb4_bin)\s*)?"
    r"(?:ROW_FORMAT\s*=\s*(?:COMPRESSED|DYNAMIC)\s*)?",
    re.IGNORECASE,
)


def _validate_raw(value):
    if not RAW_RE.fullmatch(value):
        raise InputError("unsupported raw SQL value")


def parse_row(text):
    if not text.startswith("("):
        raise InputError("row does not start with '('")
    index = 1
    values = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        if text[index] == "'":
            index += 1
            chars = []
            while index < len(text):
                char = text[index]
                if char == "\\":
                    if index + 1 >= len(text) or text[index + 1] not in ESCAPES:
                        raise InputError("unsupported or incomplete string escape")
                    chars.append(ESCAPES[text[index + 1]])
                    index += 2
                elif char == "'" and index + 1 < len(text) and text[index + 1] == "'":
                    chars.append("'")
                    index += 2
                elif char == "'":
                    index += 1
                    break
                else:
                    chars.append(char)
                    index += 1
            else:
                raise InputError("unterminated SQL string")
            values.append("".join(chars))
        else:
            start = index
            depth = 0
            quote = None
            while index < len(text):
                char = text[index]
                if quote:
                    if char == "\\":
                        index += 2
                        continue
                    if char == quote:
                        quote = None
                    index += 1
                elif char in {'"', "'", "`"}:
                    quote = char
                    index += 1
                elif char == "(":
                    depth += 1
                    index += 1
                elif char == ")" and depth:
                    depth -= 1
                    index += 1
                elif char in {",", ")"} and depth == 0:
                    break
                else:
                    index += 1
            raw = text[start:index].strip()
            if not raw:
                raise InputError("empty SQL value")
            _validate_raw(raw)
            values.append(Raw(raw))
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
        elif index < len(text) and text[index] == ")":
            return values, text[index + 1 :]
        else:
            raise InputError("expected ',' or ')' after SQL value")
    raise InputError("unterminated SQL row")


def sql_str(value):
    if isinstance(value, Raw):
        return value
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    for source, replacement in (("\0", "\\0"), ("\n", "\\n"), ("\r", "\\r"), ("\x1a", "\\Z"), ("\b", "\\b"), ("\t", "\\t")):
        escaped = escaped.replace(source, replacement)
    return "'" + escaped + "'"


def parse_insert(statement):
    match = re.match(r"INSERT\s+INTO\s+`([a-z0-9_]+)`\s+VALUES\s*", statement, re.IGNORECASE)
    if not match:
        raise InputError("INSERT must use `table` and VALUES without a column list")
    table = match.group(1).lower()
    rest = statement[match.end() :]
    rows = []
    while rest.strip():
        rest = rest.lstrip()
        row, rest = parse_row(rest)
        rows.append(row)
        rest = rest.lstrip()
        if rest.startswith(","):
            rest = rest[1:]
        elif rest:
            raise InputError("unexpected text after INSERT row")
    if not rows:
        raise InputError("INSERT has no rows")
    return table, rows


def strip_comments(text):
    out = []
    index = 0
    quote = None
    while index < len(text):
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and quote in {"'", '"'} and index + 1 < len(text):
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                if quote == "'" and index + 1 < len(text) and text[index + 1] == "'":
                    out.append(text[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
        elif char in {"'", '"', "`"}:
            quote = char
            out.append(char)
            index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise InputError("unterminated SQL comment")
            out.append("\n" * text[index : end + 2].count("\n"))
            index = end + 2
        elif char == "#" or (text.startswith("--", index) and (index + 2 == len(text) or text[index + 2].isspace())):
            end = text.find("\n", index)
            if end < 0:
                break
            out.append("\n")
            index = end + 1
        else:
            out.append(char)
            index += 1
    if quote:
        raise InputError("unterminated quote in SQL")
    return "".join(out)


def split_statements(text):
    statements = []
    start = 0
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\" and quote in {"'", '"'}:
                index += 2
                continue
            if char == quote:
                if quote == "'" and index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == ";":
            statement = text[start:index].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    if quote:
        raise InputError("unterminated quote in SQL")
    tail = text[start:].strip()
    if tail:
        raise InputError("SQL does not end at a statement boundary")
    return statements


def _balanced_body(statement):
    opening = statement.find("(")
    if opening < 0:
        raise InputError("CREATE TABLE has no column list")
    depth = 0
    quote = None
    index = opening
    while index < len(statement):
        char = statement[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return statement[opening + 1 : index], statement[index + 1 :]
        index += 1
    raise InputError("unbalanced CREATE TABLE")


def _split_top_level(value):
    parts = []
    start = 0
    depth = 0
    quote = None
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
        index += 1
    parts.append(value[start:])
    return parts


SAFE_DDL_LITERAL_RE = re.compile(r"-?[0-9]{1,4}(?:\.[0-9]{1,4})?|[0-9]{4}-[0-9]{2}-[0-9]{2}(?: [0-9]{2}:[0-9]{2}:[0-9]{2})?|")
DDL_LITERAL = r"'(?:\\.|''|[^'\\])*'"
DDL_CHARSET = r"(?:latin1|utf8|utf8mb3|utf8mb4)"
DDL_COLLATION = r"(?:latin1_swedish_ci|utf8_general_ci|utf8mb3_bin|utf8mb3_general_ci|utf8mb4_bin)"
COLUMN_DEFINITION_RE = re.compile(
    rf"\s*`[a-z0-9_]+`\s+[a-z]+"
    rf"(?:\(\s*(?:[0-9]+(?:\s*,\s*[0-9]+)?|{DDL_LITERAL}(?:\s*,\s*{DDL_LITERAL})*)\s*\))?"
    rf"(?:\s+UNSIGNED)?(?:\s+ZEROFILL)?"
    rf"(?:\s+CHARACTER\s+SET\s+{DDL_CHARSET})?(?:\s+COLLATE\s+{DDL_COLLATION})?"
    rf"(?:\s+(?:NOT\s+)?NULL)?"
    rf"(?:\s+DEFAULT\s+(?:NULL|{NUMBER}|{DDL_LITERAL}|CURRENT_TIMESTAMP(?:\(\))?))?"
    rf"(?:\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP(?:\(\))?)?"
    rf"(?:\s+AUTO_INCREMENT)?\s*",
    re.IGNORECASE,
)


def index_columns(value, table, known_columns, prefixes=False):
    component = r"`([a-z0-9_]+)`" + (r"(?:\([0-9]+\))?(?:\s+(?:ASC|DESC))?" if prefixes else "")
    names = []
    for part in value.split(","):
        match = re.fullmatch(rf"\s*{component}\s*", part, re.IGNORECASE)
        if not match or match.group(1).lower() not in known_columns.get(table, ()):
            raise InputError("unsupported index or foreign key column")
        names.append(match.group(1).lower())
    return names


def validate_create(statement, known_columns=KNOWN_COLUMNS, string_columns=STRING_COLUMNS):
    match = re.match(r"CREATE\s+TABLE\s+`?([a-z0-9_]+)`?\s*\(", statement, re.IGNORECASE)
    if not match:
        raise InputError("unsupported CREATE statement")
    table = match.group(1).lower()
    if table not in known_columns:
        raise InputError(f"unknown table: {table}")
    blocked = r"\b(?:DATA\s+DIRECTORY|INDEX\s+DIRECTORY|TABLESPACE|CONNECTION|ENCRYPTION)\b|\bCOMMENT\s*(?:=|'|\")"
    if re.search(blocked, statement, re.IGNORECASE):
        raise InputError(f"unsupported metadata in CREATE TABLE {table}")
    for literal in re.findall(r"'((?:\\.|''|[^'])*)'", statement):
        if not SAFE_DDL_LITERAL_RE.fullmatch(literal) and literal not in DDL_STRING_LITERALS.get(table, set()):
            raise InputError(f"non-allowlisted string literal in CREATE TABLE {table}")
    body, options = _balanced_body(statement)
    columns = []
    for part in _split_top_level(body):
        column = re.match(r"\s*`([a-z0-9_]+)`\s+([a-z]+)\b", part, re.IGNORECASE)
        if column:
            name = column.group(1).lower()
            sql_type = column.group(2).lower()
            expected_string = (table, name) in string_columns
            if sql_type not in STRING_SQL_TYPES | NUMERIC_SQL_TYPES or (sql_type in STRING_SQL_TYPES) != expected_string:
                raise InputError(f"unexpected SQL type for {table}.{name}: {sql_type}")
            if not COLUMN_DEFINITION_RE.fullmatch(part):
                raise InputError(f"unsupported column definition in {table}")
            columns.append(name)
            continue
        key = re.fullmatch(r"\s*(?:(?:UNIQUE|FULLTEXT)\s+)?KEY(?:\s+`[^`]+`)?\s*\((.+)\)(?:\s+USING\s+BTREE)?\s*", part, re.IGNORECASE | re.DOTALL)
        primary = re.fullmatch(r"\s*PRIMARY\s+KEY\s*\((.+)\)(?:\s+USING\s+BTREE)?\s*", part, re.IGNORECASE | re.DOTALL)
        foreign = re.fullmatch(
            r"\s*(?:CONSTRAINT\s+`[^`]+`\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+`([a-z0-9_]+)`\s*\(([^)]+)\)((?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|RESTRICT|SET\s+NULL|NO\s+ACTION))*)\s*",
            part,
            re.IGNORECASE | re.DOTALL,
        )
        if key or primary:
            index_columns((key or primary).group(1), table, known_columns, prefixes=True)
        elif foreign:
            target = foreign.group(2).lower()
            local = index_columns(foreign.group(1), table, known_columns)
            remote = index_columns(foreign.group(3), target, known_columns)
            if len(local) != len(remote):
                raise InputError(f"unknown foreign key reference in CREATE TABLE {table}")
        else:
            raise InputError(f"unsupported clause in CREATE TABLE {table}")
    if tuple(columns) != known_columns[table]:
        raise InputError(f"unknown or missing column in {table}: {tuple(columns)!r}")
    if not TABLE_OPTIONS_RE.fullmatch(options):
        raise InputError(f"unsupported table options in {table}")
    index = 0

    def rename_key(match):
        nonlocal index
        index += 1
        return f"{match.group(1)} `ix_{table}_{index}`"

    sanitized = re.sub(r"\b((?:UNIQUE\s+|FULLTEXT\s+)?KEY)\s+`[^`]+`", rename_key, statement, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b(CONSTRAINT)\s+`[^`]+`", rename_key, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+AUTO_INCREMENT\s*=\s*\d+", "", sanitized, flags=re.IGNORECASE)
    return table, sanitized


def validate_alter(statement, sequence, known_columns=KNOWN_COLUMNS):
    match = re.match(r"ALTER\s+TABLE\s+`([a-z0-9_]+)`\s+(.+)", statement, re.IGNORECASE | re.DOTALL)
    if not match:
        raise InputError("unsupported ALTER statement")
    table = match.group(1).lower()
    if table not in known_columns:
        raise InputError(f"unknown table: {table}")
    body = match.group(2).strip()
    if re.fullmatch(r"(?:ENABLE|DISABLE)\s+KEYS", body, re.IGNORECASE):
        return None
    clauses = re.split(r",\s*(?=ADD\s+CONSTRAINT\b)", body, flags=re.IGNORECASE)
    output = []
    pattern = re.compile(
        r"ADD\s+CONSTRAINT\s+`[^`]+`\s+FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+`([a-z0-9_]+)`\s*\(([^)]+)\)((?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|RESTRICT|SET\s+NULL|NO\s+ACTION))*)",
        re.IGNORECASE | re.DOTALL,
    )
    for offset, clause in enumerate(clauses):
        constraint = pattern.fullmatch(clause.strip())
        if not constraint:
            raise InputError(f"unsupported ALTER TABLE form for {table}")
        local = [name.lower() for name in re.findall(r"`([a-z0-9_]+)`", constraint.group(1), re.IGNORECASE)]
        target = constraint.group(2).lower()
        remote = [name.lower() for name in re.findall(r"`([a-z0-9_]+)`", constraint.group(3), re.IGNORECASE)]
        if target not in known_columns or any(name not in known_columns[table] for name in local) or any(name not in known_columns[target] for name in remote):
            raise InputError(f"unknown foreign key reference in {table}")
        name = f"fk_{table}_{sequence + offset + 1}"
        output.append(f"ADD CONSTRAINT `{name}` FOREIGN KEY ({constraint.group(1).strip()}) REFERENCES `{target}` ({constraint.group(3).strip()}){constraint.group(4)}")
    return f"ALTER TABLE `{table}`\n  " + ",\n  ".join(output)


def parse_dump(text, require_complete=True, known_columns=KNOWN_COLUMNS, string_columns=STRING_COLUMNS):
    if re.search(r"(?mi)^\s*DELIMITER\b", text):
        raise InputError("routines and triggers are not supported; dump without them")
    items = []
    creates = set()
    foreign_key_count = 0
    for statement in split_statements(strip_comments(text)):
        upper = statement.lstrip().upper()
        if re.search(r"\bDEFINER\s*=", statement, re.IGNORECASE):
            raise InputError("DEFINER is not supported")
        if re.match(r"CREATE\s+(?:PROCEDURE|FUNCTION|TRIGGER|EVENT)\b", statement, re.IGNORECASE):
            raise InputError("routines and triggers are not supported; dump without them")
        if upper.startswith("CREATE TABLE"):
            table, statement = validate_create(statement, known_columns, string_columns)
            if table in creates:
                raise InputError(f"duplicate CREATE TABLE for {table}")
            creates.add(table)
            items.append(("create", table, statement.strip()))
        elif upper.startswith("DROP TABLE"):
            match = re.fullmatch(r"DROP\s+TABLE\s+IF\s+EXISTS\s+`?([a-z0-9_]+)`?", statement, re.IGNORECASE)
            if not match or match.group(1).lower() not in known_columns:
                raise InputError("unsupported or unknown DROP TABLE")
            items.append(("drop", match.group(1).lower(), None))
        elif upper.startswith("INSERT"):
            table, rows = parse_insert(statement)
            if table not in known_columns:
                raise InputError(f"unknown table: {table}")
            for row in rows:
                if len(row) != len(known_columns[table]):
                    raise InputError(f"wrong column count in {table}: {len(row)}")
                for column, value in zip(known_columns[table], row):
                    if not isinstance(value, Raw) or value.upper() == "NULL":
                        continue
                    if (table, column) in string_columns or not re.fullmatch(NUMBER, value):
                        raise InputError(f"raw SQL value is not allowed in {table}.{column}")
            items.append(("insert", table, rows))
        elif upper.startswith("ALTER TABLE"):
            altered = validate_alter(statement, foreign_key_count, known_columns)
            if altered:
                foreign_key_count += altered.upper().count("ADD CONSTRAINT")
                items.append(("alter", None, altered))
        elif re.fullmatch(r"ALTER\s+DATABASE\s+`[^`]+`\s+CHARACTER\s+SET\s+(?:latin1|utf8mb4)\s+COLLATE\s+[a-z0-9_]+", statement, re.IGNORECASE) or re.fullmatch(r"LOCK\s+TABLES\s+`[a-z0-9_]+`\s+WRITE", statement, re.IGNORECASE) or re.fullmatch(r"UN" r"LOCK\s+TABLES", statement, re.IGNORECASE) or re.fullmatch(r"SET\s+(?:NAMES\s+[a-z0-9_]+|(?:FOREIGN_KEY_CHECKS|UNIQUE_CHECKS|AUTOCOMMIT)\s*=\s*[01]|SQL_MODE\s*=\s*'[-A-Z_,]*')", statement, re.IGNORECASE):
            continue
        else:
            keyword = statement.split(None, 1)[0] if statement.split() else "empty"
            raise InputError(f"unsupported SQL statement: {keyword}")
    if require_complete and creates != set(known_columns):
        missing = sorted(set(known_columns) - creates)
        extra = sorted(creates - set(known_columns))
        raise InputError(f"schema is not a complete supported NicTool dump; missing={missing!r} extra={extra!r}")
    return items


HISTORY_TABLES = frozenset(table for table in KNOWN_COLUMNS if table.endswith("_log") and table not in DROP_ROWS)
RETENTION_PROFILES = {"full", "historical-patterns"}
HISTORY_ROWS_PER_SHAPE = 2


def _length_shape(length):
    for limit in (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 1024):
        if length <= limit:
            return limit
    return "long"


def _raw_retention_shape(column, value):
    upper = value.upper()
    if upper == "NULL":
        return ("null",)
    if column == "type_id":
        return ("type", value)
    if value in {"-1", "0", "1"}:
        return ("number", value)
    if re.fullmatch(NUMBER, value):
        return ("number", "negative" if value.startswith("-") else "decimal" if any(char in value for char in ".eE") else "integer")
    if upper.startswith("POINT("):
        return ("point",)
    if upper.startswith("0X"):
        return ("hex", _length_shape(len(value)))
    return ("bit", _length_shape(len(value)))


def _text_retention_shape(table, column, value):
    if value in ROW_STRING_LITERALS.get((table, column), set()):
        return ("literal", value)
    flags = []
    if not value:
        return ("empty",)
    if any(ord(char) > 127 for char in value):
        flags.append("unicode")
    if any(char in value for char in "\0\n\r\x1a\b\t"):
        flags.append("control")
    if Mapper.EMAIL_RE.search(value):
        flags.append("email")
    for candidate in Mapper.IP4_RE.findall(value):
        parts = candidate.split(".")
        if all(int(part) <= 255 for part in parts):
            flags.append(f"ipv4-{Mapper._ip4_category(parts)}-{len(parts)}")
    for match in Mapper.IP6_RE.finditer(value):
        try:
            address = ipaddress.IPv6Address(match.group(0))
        except ValueError:
            continue
        if address.is_link_local:
            flags.append("ipv6-link-local")
        elif address in ipaddress.IPv6Network("fc00::/7"):
            flags.append("ipv6-ula")
        elif address.is_multicast:
            flags.append("ipv6-multicast")
        else:
            flags.append("ipv6-global")
    if Mapper.HOST_RE.search(value):
        flags.append("hostname")
    if "*" in value:
        flags.append("wildcard")
    if re.search(r"(?:^|\.)_[a-z0-9_-]+", value, re.IGNORECASE):
        flags.append("underscore-label")
    if value.rstrip(".").lower().endswith((".in-addr.arpa", ".ip6.arpa")):
        flags.append("reverse-name")
    if re.search(r"(?<![a-z0-9_])_?[0-9a-f]{16,}(?![a-z0-9_])", value, re.IGNORECASE):
        flags.append("opaque-label")
    if Mapper.DKIM_RE.search(value):
        flags.append("dkim")
    if Mapper.VERIFICATION_RE.search(value) or re.search(r"\bMS\s*=\s*ms\d+\b", value, re.IGNORECASE):
        flags.append("verification")
    if Mapper.TOKEN_RE.search(value):
        flags.append("token")
    return ("text", _length_shape(len(value)), *sorted(set(flags)))


def retention_shape(table, row, columns):
    return tuple(_raw_retention_shape(column, value) if isinstance(value, Raw) else _text_retention_shape(table, column, value) for column, value in zip(columns, row))


def retention_plan(items, known_columns=KNOWN_COLUMNS, profile="full"):
    if profile not in RETENTION_PROFILES:
        raise InputError(f"unsupported retention profile: {profile}")
    if profile == "full":
        return {}, {}
    table_rows = {}
    for kind, table, payload in items:
        if kind == "insert" and table in HISTORY_TABLES:
            table_rows.setdefault(table, []).extend(payload)
    kept = {}
    removed = {}
    for table, rows in table_rows.items():
        shapes = {}
        for index, row in enumerate(rows):
            shapes.setdefault(retention_shape(table, row, known_columns[table]), []).append(index)
        indexes = set()
        for matches in shapes.values():
            indexes.update(matches[:1])
            indexes.update(matches[-1:])
        kept[table] = indexes
        if len(indexes) < len(rows):
            removed[table] = len(rows) - len(indexes)
    return kept, removed


def retention_metadata(profile, removed):
    return {
        "profile": profile,
        "tables": sorted(HISTORY_TABLES) if profile == "historical-patterns" else [],
        "dropped_rows": dict(sorted(removed.items())),
        "method": "first and last source row for each structural shape" if profile == "historical-patterns" else "all non-session rows",
        "rows_per_shape": HISTORY_ROWS_PER_SHAPE if profile == "historical-patterns" else "all",
    }


def column_limits(items):
    limits = {}
    for kind, table, payload in items:
        if kind != "create":
            continue
        body, _ = _balanced_body(payload)
        for part in _split_top_level(body):
            column = re.match(r"\s*`([a-z0-9_]+)`\s+(.+)", part, re.IGNORECASE | re.DOTALL)
            if not column:
                continue
            sized = re.match(r"(?:VAR)?CHAR\s*\(\s*(\d+)\s*\)", column.group(2), re.IGNORECASE)
            if sized:
                limits[(table, column.group(1).lower())] = int(sized.group(1))
    return limits


def _change(row, columns, name, function):
    index = columns.index(name)
    if not isinstance(row[index], Raw):
        row[index] = function(row[index])


SAFE_LITERAL = re.compile(r"(?:|[+-]?\d+(?:\.\d+)?|\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d:\d\d)?|NULL)")


def numeric_id_list(value):
    if not re.fullmatch(r"\d+(?:,\d+)*", value):
        raise InputError("nt_perm.usable_ns is not a numeric id list")
    return value


def static_string(table, column, value):
    if value not in ROW_STRING_LITERALS[(table, column)]:
        raise InputError(f"non-allowlisted static value in {table}.{column}")
    return value


def rewrite_row(table, row, mapper, people, password, limits=None, known_columns=KNOWN_COLUMNS, static_rows=STATIC_ROWS, db_version="2.41"):
    columns = known_columns[table]
    result = list(row)
    handled = set()

    def change(name, function):
        _change(result, columns, name, function)
        handled.add(name)

    if table in static_rows:
        if tuple(str(value) for value in result) not in static_rows[table]:
            raise InputError(f"non-allowlisted static lookup row in {table}")
        handled.update(columns)
    elif table in {"nt_zone", "nt_zone_log"}:
        for name in ("zone", "mailaddr"):
            change(name, mapper.host)
        for name in ("description", "location"):
            if name in columns:
                change(name, lambda value: mapper.words(value, people))
        if table == "nt_zone_log":
            change("action", lambda value: static_string(table, "action", value))
    elif table in {"nt_zone_record", "nt_zone_record_log"}:
        zone = mapper.zones.get(str(result[columns.index("nt_zone_id")]))
        change("name", lambda value: mapper.record_host(value, zone))
        record_type = str(result[columns.index("type_id")])
        if record_type in TXT_TYPES:
            change("address", lambda value: mapper.txt(value, people))
        elif record_type == "1":
            change("address", mapper.ip4_field)
        elif record_type == "28":
            change("address", mapper.ip6_field)
        elif record_type == "29":
            change("address", mapper.loc)
        elif record_type in HOST_TYPES:
            change("address", lambda value: mapper.record_host(value, zone))
        else:
            change("address", lambda value: mapper.txt(value, people))
        for name in ("description", "location"):
            change(name, lambda value: mapper.words(value, people))
        change("other", lambda value: value if re.fullmatch(r"[\d\s]*", value) else mapper.txt(value, people))
        if table == "nt_zone_record_log":
            change("action", lambda value: static_string(table, "action", value))
    elif table in {"nt_user", "nt_user_log"}:
        for name, function in (("first_name", mapper.first), ("last_name", mapper.last), ("username", mapper.username), ("email", mapper.email)):
            change(name, function)
        if table == "nt_user":
            username = result[columns.index("username")]
            result[columns.index("pass_salt")], result[columns.index("password")] = password(username)
        else:
            change("action", lambda value: static_string(table, "action", value))
            result[columns.index("pass_salt")] = ""
            result[columns.index("password")] = ""
        handled.update({"pass_salt", "password"})
    elif table in {"nt_group", "nt_group_log"}:
        change("name", lambda value: value if value == "NicTool" else (mapper.host(value) if "." in value else mapper.label(value)))
        if table == "nt_group_log":
            change("action", lambda value: static_string(table, "action", value))
    elif table in {"nt_nameserver", "nt_nameserver_log"}:
        functions = (("name", mapper.host), ("description", lambda value: mapper.words(value, people)), ("address", mapper.ip4_field), ("address6", mapper.ip6_field), ("logdir", lambda value: mapper.words(value, people)), ("datadir", lambda value: mapper.words(value, people)))
        for name, function in functions:
            change(name, function)
        if table == "nt_nameserver":
            change("remote_login", mapper.username)
            change("rsync_user", mapper.username)
            change("export_status", lambda value: mapper.words(value, people))
        else:
            change("action", lambda value: static_string(table, "action", value))
            change("export_format", lambda value: mapper.words(value, people))
    elif table == "nt_nameserver_export_log":
        change("message", lambda value: mapper.words(value, people))
    elif table == "nt_perm":
        change("perm_name", lambda value: mapper.words(value, people))
        change("usable_ns", numeric_id_list)
    elif table == "nt_options":
        option_name = result[columns.index("option_name")]
        option_value = result[columns.index("option_value")]
        if isinstance(option_name, Raw) or isinstance(option_value, Raw):
            raise InputError("nt_options names and values must be SQL strings")
        if option_name == "db_version":
            if option_value != db_version:
                raise InputError(f"expected NicTool db_version {db_version}")
        elif option_name == "session_timeout":
            if not re.fullmatch(r"\d+", option_value):
                raise InputError("session_timeout is not numeric")
        elif option_name == "default_group":
            result[columns.index("option_value")] = option_value if option_value == "NicTool" else mapper.label(option_value)
        else:
            result[columns.index("option_name")] = mapper.words(option_name, people)
            result[columns.index("option_value")] = mapper.words(option_value, people)
        handled.update({"option_name", "option_value"})
    elif table in {"nt_delegate", "nt_delegate_log"}:
        for name in ("delegated_by_name", "nt_user_name", "action", "nt_object_type"):
            if name in columns:
                function = mapper.username if name.endswith("_name") else lambda value, column=name: static_string(table, column, value)
                change(name, function)
    elif table == "nt_user_global_log":
        for name in ("action", "object", "target"):
            change(name, lambda value, column=name: static_string(table, column, value))
        for name in ("target_name", "title", "description"):
            change(name, lambda value: mapper.words(value, people))

    for name, value in zip(columns, result):
        if name in handled or isinstance(value, Raw):
            continue
        if not SAFE_LITERAL.fullmatch(value):
            raise InputError(f"unclassified string content in {table}.{name}")
    for name, value in zip(columns, result):
        limit = (limits or {}).get((table, name))
        if limit is None or isinstance(value, Raw) or len(value) <= limit:
            continue
        if (table, name) not in TRUNCATABLE_FIELDS:
            raise InputError(f"mapped value exceeds {table}.{name} length")
        result[columns.index(name)] = mapper.label("x" + value)[:limit]
        mapper.seen["truncated_text"] += 1
    return result


def pbkdf2(secret, username):
    salt = base64.b64encode(hashlib.sha256(f"{secret}:{username}".encode()).digest())[:16].decode()
    digest = hashlib.pbkdf2_hmac("sha512", PASSWORD.encode(), salt.encode(), 5000, 32).hex()
    return salt, digest


def source_reservations(items, known_columns=KNOWN_COLUMNS):
    reserved = set()
    for kind, table, payload in items:
        if kind != "insert" or table in STATIC_ROWS:
            continue
        columns = known_columns[table]
        for row in payload:
            for column, value in zip(columns, row):
                if not isinstance(value, str) or isinstance(value, Raw) or value in ROW_STRING_LITERALS.get((table, column), set()):
                    continue
                reserved.add(value.casefold())
                reserved.update(word.casefold() for word in Mapper.WORD_RE.findall(value))
                reserved.update(label.casefold() for host in Mapper.HOST_RE.findall(value) for label in host.rstrip(".").split("."))
                reserved.update(token.casefold() for token in Mapper.TOKEN_RE.findall(value))
    return reserved


def discover_zones(items, mapper, known_columns=KNOWN_COLUMNS):
    for table in ("nt_zone", "nt_zone_log"):
        columns = known_columns[table]
        for kind, item_table, payload in items:
            if kind != "insert" or item_table != table:
                continue
            for row in payload:
                values = dict(zip(columns, row))
                if not isinstance(values["zone"], Raw):
                    mapper.zones.setdefault(str(values["nt_zone_id"]), values["zone"])


def discover_people(items, mapper, known_columns=KNOWN_COLUMNS):
    people = {}
    for kind, table, payload in items:
        if kind != "insert" or table not in {"nt_user", "nt_group"}:
            continue
        columns = known_columns[table]
        for row in payload:
            values = dict(zip(columns, row))
            if table == "nt_user":
                first, last, username = (values[name] for name in ("first_name", "last_name", "username"))
                if isinstance(first, str) and not isinstance(first, Raw):
                    people[first] = mapper.first(first)
                if isinstance(last, str) and not isinstance(last, Raw):
                    people[last] = mapper.last(last)
                if all(isinstance(value, str) and not isinstance(value, Raw) and value for value in (first, last)):
                    people[f"{first} {last}"] = f"{mapper.first(first)} {mapper.last(last)}"
                if isinstance(username, str) and not isinstance(username, Raw):
                    people[username] = mapper.username(username)
            else:
                name = values["name"]
                if isinstance(name, str) and not isinstance(name, Raw) and name != "NicTool":
                    people[name] = mapper.host(name) if "." in name else mapper.label(name)
    return sorted(people.items(), key=lambda item: len(item[0]), reverse=True)


def render_insert(table, rows):
    rendered = ["(" + ",".join(sql_str(value) for value in row) + ")" for row in rows]
    return f"INSERT INTO `{table}` VALUES\n" + ",\n".join(rendered) + ";"


def anonymize_sql(
    text,
    secret,
    contributor="anonymous",
    require_complete=True,
    source_alias="private",
    source_date="undated",
    db_version="2.41",
    static_profile=None,
    retention_profile="full",
):
    if len(secret.encode()) < 32:
        raise InputError("CORPUS_SECRET must contain at least 32 bytes")
    if not CONTRIBUTOR_RE.fullmatch(contributor):
        raise InputError("contributor must be a 1-40 character lower-case alias")
    if not CONTRIBUTOR_RE.fullmatch(source_alias):
        raise InputError("source alias must be a 1-40 character lower-case alias")
    if not SOURCE_DATE_RE.fullmatch(source_date):
        raise InputError("source date must be YYYY-MM-DD or undated")
    if db_version not in SCHEMA_COLUMNS:
        raise InputError(f"unsupported NicTool db version: {db_version}")
    static_profile = static_profile or db_version
    if static_profile not in STATIC_PROFILES:
        raise InputError(f"unsupported static lookup profile: {static_profile}")
    if STATIC_PROFILE_VERSIONS[static_profile] != db_version:
        raise InputError(f"static lookup profile {static_profile} is not valid for NicTool db version {db_version}")
    if retention_profile not in RETENTION_PROFILES:
        raise InputError(f"unsupported retention profile: {retention_profile}")
    if re.search(r"[\ue000-\ue109]", text):
        raise InputError("source contains reserved parser marker characters")
    known_columns = SCHEMA_COLUMNS[db_version]
    string_columns = SCHEMA_STRING_COLUMNS[db_version]
    static_rows = STATIC_PROFILES[static_profile]
    items = parse_dump(text, require_complete=require_complete, known_columns=known_columns, string_columns=string_columns)
    kept_history, retention_dropped = retention_plan(items, known_columns, retention_profile)
    mapper = Mapper(secret, source_reservations(items, known_columns))
    people = discover_people(items, mapper, known_columns)
    discover_zones(items, mapper, known_columns)
    limits = column_limits(items)
    output = ["SET NAMES utf8mb4;", "SET FOREIGN_KEY_CHECKS=0;"]
    counts = Counter()
    source_counts = Counter()
    dropped = Counter()
    table_offsets = Counter()
    detected_db_version = None
    for kind, table, payload in items:
        if kind == "drop":
            output.append(f"DROP TABLE IF EXISTS `{table}`;")
        elif kind == "create" or kind == "alter":
            output.append(payload + ";")
        elif kind == "insert":
            source_counts[table] += len(payload)
            if table in DROP_ROWS:
                dropped[table] += len(payload)
                continue
            if table in kept_history:
                offset = table_offsets[table]
                source_length = len(payload)
                payload = [row for index, row in enumerate(payload, offset) if index in kept_history[table]]
                table_offsets[table] += source_length
                if not payload:
                    continue
            rows = [rewrite_row(table, row, mapper, people, lambda username: pbkdf2(secret, username), limits, known_columns, static_rows, db_version) for row in payload]
            if table == "nt_options":
                columns = known_columns[table]
                for row in rows:
                    if row[columns.index("option_name")] == "db_version":
                        detected_db_version = row[columns.index("option_value")]
            counts[table] += len(rows)
            output.append(render_insert(table, rows))
    output.append("SET FOREIGN_KEY_CHECKS=1;")
    if require_complete and detected_db_version != db_version:
        raise InputError(f"complete dump has no db_version {db_version} option row")
    body = "\n\n".join(output) + "\n"
    manifest = {
        "format": 2,
        "license": LICENSE,
        "copyright": COPYRIGHT,
        "tool": {"name": "anonymize.py", "version": VERSION},
        "provenance": {"contributor": contributor, "source_alias": source_alias, "source_date": source_date, "raw_source": "not retained"},
        "input_contract": {"db_version": db_version, "insert_layouts": ["extended", "non-extended"], "raw_values": "NULL or numeric values in numeric columns", "routines": "rejected", "triggers": "rejected", "unknown_sql": "rejected"},
        "rows": dict(sorted(counts.items())),
        "source_rows": dict(sorted(source_counts.items())),
        "dropped": {"tables": sorted(DROP_ROWS), "rows": dict(sorted(dropped.items())), "reason": "session material"},
        "retention": retention_metadata(retention_profile, retention_dropped),
        "mapped": dict(sorted(mapper.seen.items())),
        "passwords": {"value": PASSWORD, "scheme": "PBKDF2-SHA512", "rounds": 5000, "bytes": 32},
        "address_policy": {
            "ipv4_public": "198.18.0.0/15",
            "ipv4_private": "same RFC1918 block as the source",
            "ipv4_special": "link-local, loopback, carrier-grade, multicast, and unspecified keep their class",
            "ipv6_global": "2001:db8::/32",
            "ipv6_private": "ULA stays ULA; link-local and site-local keep their class",
            "ipv6_special": "multicast keeps its flags and scope; loopback and unspecified are unchanged",
        },
        "dns_target_policy": "all names use one label mapping; in-corpus CNAME, MX, NS, PTR, SRV, and DNAME targets remain internally consistent",
        "static_lookup_allowlist": sorted(static_rows),
        "static_lookup_profile": static_profile,
        "static_string_allowlist": sorted(f"{table}.{column}" for table, column in ROW_STRING_LITERALS),
        "reproducibility": "same input bytes, secret, contributor, source alias, source date, db version, static profile, retention profile, and tool version produce identical SQL, gzip, and manifest bytes",
    }
    return body, manifest


def deterministic_gzip(data):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as stream:
        stream.write(data)
    return output.getvalue()


def _write_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    descriptor, temporary = tempfile.mkstemp(prefix=".anonymize-", dir=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _manifest_path(destination):
    return re.sub(r"\.sql(?:\.gz)?$", "", destination) + ".manifest.json"


def read_secret(environment, secret_file):
    secret = environment.get("CORPUS_SECRET")
    if secret and secret_file:
        raise InputError("set CORPUS_SECRET or --secret-file, not both")
    if secret_file:
        if stat.S_IMODE(os.stat(secret_file).st_mode) & 0o077:
            raise InputError("secret file must be mode 0600")
        with open(secret_file, "r", encoding="utf8") as stream:
            secret = stream.read().rstrip("\n")
    if not secret:
        raise InputError("set CORPUS_SECRET or pass a mode-0600 --secret-file")
    if len(secret.encode()) < 32:
        raise InputError("secret must contain at least 32 bytes")
    return secret


def run(
    source,
    destination,
    secret,
    contributor,
    force=False,
    source_alias="private",
    source_date="undated",
    db_version="2.41",
    static_profile=None,
    retention_profile="full",
):
    if not re.search(r"\.sql(?:\.gz)?$", destination):
        raise InputError("destination must end in .sql or .sql.gz")
    source_path = os.path.realpath(source)
    destination_path = os.path.realpath(destination)
    manifest_path = _manifest_path(destination)
    if source_path in {destination_path, os.path.realpath(manifest_path)}:
        raise InputError("source, destination, and manifest must be different files")
    if stat.S_IMODE(os.stat(source).st_mode) & 0o077:
        raise InputError("source dump must be mode 0600")
    opener = gzip.open if source.endswith(".gz") else open
    with opener(source, "rt", encoding="utf8", newline="") as stream:
        source_text = stream.read()
    body, manifest = anonymize_sql(
        source_text,
        secret,
        contributor,
        source_alias=source_alias,
        source_date=source_date,
        db_version=db_version,
        static_profile=static_profile,
        retention_profile=retention_profile,
    )
    sql_bytes = body.encode()
    corpus_bytes = deterministic_gzip(sql_bytes) if destination.endswith(".gz") else sql_bytes
    source_bytes = source_text.encode()
    manifest["source"] = {"sha256": hashlib.sha256(source_bytes).hexdigest(), "bytes": len(source_bytes)}
    manifest["corpus"] = {"sha256": hashlib.sha256(corpus_bytes).hexdigest(), "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(), "compressed": destination.endswith(".gz"), "bytes": len(corpus_bytes), "sql_bytes": len(sql_bytes)}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if (os.path.exists(destination) or os.path.exists(manifest_path)) and not force:
        raise InputError("destination or manifest exists; pass --force to replace both")
    _write_atomic(destination, corpus_bytes)
    _write_atomic(manifest_path, manifest_bytes)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--secret-file", help="mode-0600 file containing the HMAC key")
    parser.add_argument("--contributor", default="anonymous")
    parser.add_argument("--source-alias", default="private")
    parser.add_argument("--source-date", default="undated")
    parser.add_argument("--db-version", choices=sorted(SCHEMA_COLUMNS), default="2.41")
    parser.add_argument("--static-profile", choices=sorted(STATIC_PROFILES))
    parser.add_argument("--retention-profile", choices=sorted(RETENTION_PROFILES), default="full")
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        secret = read_secret(os.environ, arguments.secret_file)
        manifest = run(
            arguments.source,
            arguments.destination,
            secret,
            arguments.contributor,
            arguments.force,
            arguments.source_alias,
            arguments.source_date,
            arguments.db_version,
            arguments.static_profile,
            arguments.retention_profile,
        )
    except (InputError, OSError, UnicodeError) as error:
        parser.exit(1, f"anonymize.py: {error}\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
