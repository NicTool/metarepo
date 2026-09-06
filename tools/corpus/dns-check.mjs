// Copyright (c) 2026, The NicTool Contributors

import fs from 'node:fs'
import { pathToFileURL } from 'node:url'
import * as RR from '@nictool/dns-resource-record'
import { ZONE } from '@nictool/dns-zone'

const names = new RR.default(null)
const fqdn = (value) => names.fullyQualify(value)

export function legacyOwner(value, zone) {
  const absolute = zone && (
    value.toLowerCase() === zone.toLowerCase() ||
    value.toLowerCase().endsWith('.' + zone.toLowerCase())
  )
  return names.fullyQualify(value, absolute ? undefined : fqdn(zone))
}

function construct({ row, zone }) {
  const type = RR.typeMap[Number(row.type_id)]
  const Record = RR.classFor(Number(row.type_id))
  if (Record === RR.UNKNOWN) return null
  const args = { ...row, type, owner: legacyOwner(row.name, zone?.zone) }
  for (const key of ['ttl', 'weight', 'priority']) {
    if (args[key] !== null && args[key] !== undefined && args[key] !== '') args[key] = Number(args[key])
  }
  RR.unApplyMap(args, RR.getMap(type))
  for (const field of Record.rdataFields ?? []) {
    if (Array.isArray(field) && field[1] === 'fqdn') args[field[0]] = fqdn(args[field[0]])
  }
  return new Record(args)
}

export function checkRecord(entry) {
  let record
  try {
    record = construct(entry)
    if (!record) return { stage: 'unsupported-type' }
  } catch {
    return { stage: 'construction' }
  }
  try {
    const bind = record.toBind()
    if (record.constructor.fromBind(bind).toBind() !== bind) return { stage: 'bind-roundtrip-mismatch' }
  } catch {
    return { stage: 'bind-roundtrip' }
  }
  return { stage: 'pass' }
}

export function compare(before, after) {
  if (!before) return after.stage === 'pass' ? 'unpaired-pass' : 'unclassified-finding'
  if (before.stage === 'pass') return after.stage === 'pass' ? 'pass' : 'regression'
  if (after.stage === 'pass') return 'changed-to-valid'
  return before.stage === after.stage ? 'both-failed' : 'changed-finding'
}

function checkZone(zone, entries) {
  try {
    const soa = { owner: fqdn(zone.zone), mname: fqdn(zone.mname), rname: fqdn(zone.mailaddr) }
    for (const key of ['ttl', 'serial', 'refresh', 'retry', 'expire', 'minimum']) soa[key] = Number(zone[key])
    const target = new ZONE({ origin: fqdn(zone.zone) })
    target.addRR(new RR.SOA(soa))
    for (const entry of entries) {
      const record = construct(entry)
      if (!record) return { stage: 'unsupported-type' }
      target.addRR(record)
    }
    return { stage: 'pass' }
  } catch {
    return { stage: 'zone-validation' }
  }
}

export function checkCorpus(data) {
  if (data.format !== 1 || !Array.isArray(data.records) || !Array.isArray(data.zones))
    throw new Error('unsupported DNS input contract')
  const report = {
    records: { total: 0, comparisons: {}, stages: {} },
    zones: { total: 0, comparisons: {}, before: { passed: 0, failed: 0 }, after: { passed: 0, failed: 0 } },
  }
  const increment = (object, key) => {
    object[key] = (object[key] ?? 0) + 1
  }
  const byZone = { before: new Map(), after: new Map() }
  for (const pair of data.records) {
    const before = pair.before ? checkRecord(pair.before) : null
    const after = checkRecord(pair.after)
    report.records.total++
    increment(report.records.comparisons, compare(before, after))
    increment(report.records.stages, `${pair.after.table}:${Number(pair.after.row.type_id)}:${after.stage}`)
    for (const side of ['before', 'after']) {
      const entry = pair[side]
      if (!entry || entry.table !== 'nt_zone_record' || Number(entry.row.deleted)) continue
      const id = String(entry.row.nt_zone_id)
      if (!byZone[side].has(id)) byZone[side].set(id, [])
      byZone[side].get(id).push(entry)
    }
  }
  for (const pair of data.zones) {
    if (Number(pair.after.deleted)) continue
    const results = {}
    for (const side of ['before', 'after']) {
      const zone = pair[side]
      if (!zone) continue
      results[side] = checkZone(zone, byZone[side].get(String(zone.nt_zone_id)) ?? [])
      increment(report.zones[side], results[side].stage === 'pass' ? 'passed' : 'failed')
    }
    report.zones.total++
    increment(report.zones.comparisons, compare(results.before, results.after))
  }
  return report
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const report = checkCorpus(JSON.parse(fs.readFileSync(process.argv[2], 'utf8')))
    console.log(JSON.stringify(report, null, 2))
    const findings = [report.records.comparisons, report.zones.comparisons].some((counts) =>
      Object.entries(counts).some(([key, count]) => count && !['pass', 'unpaired-pass'].includes(key)),
    )
    process.exitCode = findings ? 1 : 0
  } catch {
    console.error('DNS corpus check could not read or process its input')
    process.exitCode = 2
  }
}
