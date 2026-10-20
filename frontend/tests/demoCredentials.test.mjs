import assert from 'node:assert/strict'
import test from 'node:test'
import { parseAdminCredentials } from '../scripts/demoCredentials.mjs'

test('reads the configured local admin username and password without altering either value', () => {
  const credentials = parseAdminCredentials([
    '# local credentials',
    'ERP_ADMIN_USERNAME=admin',
    'ERP_ADMIN_PASSWORD=Local-Admin-Password-99',
  ].join('\n'))

  assert.deepEqual(credentials, {
    username: 'admin',
    password: 'Local-Admin-Password-99',
  })
})

test('does not offer demo credentials when the local password is missing', () => {
  assert.equal(parseAdminCredentials('ERP_ADMIN_USERNAME=admin\n'), null)
})

test('does not mistake similarly named environment variables for admin credentials', () => {
  assert.equal(parseAdminCredentials('OTHER_USERNAME=admin\nOTHER_PASSWORD=secret\n'), null)
})
