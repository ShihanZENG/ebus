import { readFileSync } from 'node:fs'

export function parseAdminCredentials(contents) {
  const values = new Map()
  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const separator = line.indexOf('=')
    if (separator < 0) continue
    values.set(line.slice(0, separator).trim(), line.slice(separator + 1).trim())
  }
  const username = values.get('ERP_ADMIN_USERNAME')
  const password = values.get('ERP_ADMIN_PASSWORD')
  return username && password ? { username, password } : null
}

export function loadAdminCredentials(envPath) {
  try {
    return parseAdminCredentials(readFileSync(envPath, 'utf8'))
  } catch {
    return null
  }
}
