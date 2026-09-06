// Copyright (c) 2026, The NicTool Contributors

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { checkRecord, compare, checkCorpus, legacyOwner } from './dns-check.mjs'

const zone = {
  nt_zone_id: '1',
  zone: 'example.test',
  mailaddr: 'hostmaster.example.test',
  serial: '1',
  refresh: '3600',
  retry: '600',
  expire: '86400',
  minimum: '300',
  ttl: '300',
  deleted: '0',
  mname: 'ns.example.test',
}
const record = (type, address, fields = {}) => ({
  table: 'nt_zone_record',
  row: {
    nt_zone_id: '1',
    name: 'www',
    type_id: String(type),
    address,
    ttl: '300',
    weight: '0',
    priority: '0',
    other: '',
    deleted: '0',
    ...fields,
  },
  zone,
})

test('legacy absolute owners without a trailing dot are not qualified twice', () => {
  for (const value of ['www', 'www.example.test', 'www.example.test.']) {
    assert.equal(legacyOwner(value, 'example.test'), 'www.example.test.')
  }
  for (const value of ['@', 'example.test', 'example.test.']) {
    assert.equal(legacyOwner(value, 'example.test'), 'example.test.')
  }
})

test('NicTool mappings feed record constructors and BIND round trips', () => {
  for (const entry of [
    record(1, '198.18.1.2'),
    record(28, '2001:db8::2'),
    record(5, 'target.example.test.'),
    record(15, 'mx.example.test.', { weight: '10' }),
    record(16, 'synthetic text'),
    record(33, 'srv.example.test.', { weight: '20', priority: '10', other: '443' }),
  ]) {
    assert.equal(checkRecord(entry).stage, 'pass')
  }
})

test('old defects and new failures stay distinguishable', () => {
  const valid = checkRecord(record(1, '198.18.1.2'))
  const invalid = checkRecord(record(1, '8.9'))
  assert.equal(compare(invalid, invalid), 'both-failed')
  assert.equal(compare(valid, invalid), 'regression')
  assert.equal(compare(invalid, valid), 'changed-to-valid')
  assert.equal(compare(null, invalid), 'unclassified-finding')
})

test('unimplemented record types are not called passing', () => {
  assert.equal(checkRecord(record(65000, 'opaque')).stage, 'unsupported-type')
})

test('TXT presentation escapes survive BIND round trips', () => {
  for (const address of [
    'quote"value',
    'back\\slash',
    'line\nbreak',
    'tab\tvalue',
    'carriage\rreturn',
    'a\u0000b',
    'a\u001ab',
  ]) {
    assert.equal(checkRecord(record(16, address)).stage, 'pass')
  }
})

test('zone checks exercise CNAME coexistence without exposing names', () => {
  const rows = [record(1, '198.18.1.2'), record(5, 'target.example.test.')]
  const report = checkCorpus({
    format: 1,
    records: rows.map((after) => ({ after })),
    zones: [{ after: zone }],
  })
  assert.equal(report.zones.after.failed, 1)
  assert.equal(report.records.total, 2)
  assert.equal(JSON.stringify(report).includes('example.test'), false)
})

test('history is checked individually, never combined into a current zone', () => {
  const after = { ...record(5, 'target.example.test.'), table: 'nt_zone_record_log' }
  const report = checkCorpus({ format: 1, records: [{ after }], zones: [{ after: zone }] })
  assert.equal(report.records.total, 1)
  assert.equal(report.zones.after.failed, 0)
})
