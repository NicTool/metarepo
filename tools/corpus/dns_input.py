# Copyright (c) 2026, The NicTool Contributors

import argparse
import gzip
import json
import os

import anonymize
import audit
from schema import SCHEMA_COLUMNS, SCHEMA_STRING_COLUMNS


def snapshot(path, version, retention):
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf8') as stream:
        items = anonymize.parse_dump(stream.read(), known_columns=SCHEMA_COLUMNS[version], string_columns=SCHEMA_STRING_COLUMNS[version])
    kept, _ = anonymize.retention_plan(items, SCHEMA_COLUMNS[version], retention)
    tables = {}
    for kind, table, rows in items:
        if kind == 'insert':
            tables.setdefault(table, []).extend(rows)
    for table, rows in tables.items():
        tables[table] = [dict(zip(SCHEMA_COLUMNS[version][table], [None if isinstance(value, anonymize.Raw) and value.upper() == 'NULL' else value for value in row])) for index, row in enumerate(rows) if table not in kept or index in kept[table]]
    zones = {row['nt_zone_id']: row.copy() for row in tables.get('nt_zone', [])}
    servers = {row['nt_nameserver_id']: row for row in tables.get('nt_nameserver', [])}
    for link in tables.get('nt_zone_nameserver', []):
        zone = zones.get(link['nt_zone_id'])
        server = servers.get(link['nt_nameserver_id'])
        if zone is not None and server is not None:
            zone.setdefault('mname', server['name'])
    records = []
    for table in ('nt_zone_record', 'nt_zone_record_log'):
        for row in tables.get(table, []):
            records.append({'table': table, 'row': row, 'zone': zones.get(row['nt_zone_id'])})
    return records, list(zones.values())


def build(corpus, manifest_path, source=None):
    report = audit.audit_paths(corpus, manifest_path, source_path=source, require_source=bool(source))
    if report['status'] != 'PASS':
        raise anonymize.InputError('privacy audit failed before DNS validation')
    with open(manifest_path, encoding='utf8') as stream:
        manifest = json.load(stream)
    version = manifest['input_contract']['db_version']
    after_records, after_zones = snapshot(corpus, version, 'full')
    before_records, before_zones = snapshot(source, version, manifest['retention']['profile']) if source else ([], [])
    output = {'format': 1, 'audit': report}
    for name, before, after in (('records', before_records, after_records), ('zones', before_zones, after_zones)):
        if source and len(before) != len(after):
            raise anonymize.InputError('DNS source pairing count mismatch')
        output[name] = [{'before': before[index], 'after': value} if source else {'after': value} for index, value in enumerate(after)]
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('corpus')
    parser.add_argument('manifest')
    parser.add_argument('output')
    parser.add_argument('--source')
    args = parser.parse_args()
    try:
        data = build(args.corpus, args.manifest, args.source)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
            json.dump(data, stream)
    except (anonymize.InputError, OSError, ValueError, KeyError):
        parser.exit(2, 'DNS input preparation failed; no source values were logged\n')
