import { expect, test, type Page } from '@playwright/test'


const agentProfile = {
  id: '00000000-0000-4000-8000-000000000201',
  login_id: 'agt-test',
  full_name: 'Test Agent',
  role: 'AGENT',
  must_change_password: false,
  taluk_name: 'Kasargod',
  bank: null,
}

const adminProfile = {
  id: '00000000-0000-4000-8000-000000000202',
  login_id: 'admin',
  full_name: 'System Administrator',
  role: 'ADMIN',
  must_change_password: false,
}

const collection = {
  id: '00000000-0000-4000-8000-000000000301',
  receipt_number: 'RC-TEST-001',
  member_id: '00000000-0000-4000-8000-000000000302',
  member_name: 'Test Member',
  label: 'Permanent membership',
  collection_type: 'PERMANENT_MEMBERSHIP',
  amount: 500,
  method: 'CASH',
  collected_at: '2026-09-12T10:00:00+05:30',
  status: 'RECORDED',
}

const handover = {
  id: '00000000-0000-4000-8000-000000000401',
  deposit_number: 'HND-TEST-001',
  agent_name: 'Test Agent',
  agent_phone: '9447645196',
  taluk_name: 'Kasargod',
  bank_name: '',
  bank_last4: '',
  calculated_total: 500,
  declared_deposit_amount: 500,
  submitted_at: '2026-09-12T11:00:00+05:30',
  status: 'SUBMITTED',
  collection_ids: [collection.id],
  bank_reference: null,
  handover_note: 'Cash counted and handed over',
  version: 1,
}

const talukId = '00000000-0000-4000-8000-000000000501'
const obligationId = '00000000-0000-4000-8000-000000000502'
const member = {
  id: collection.member_id,
  profile_id: '00000000-0000-4000-8000-000000000503',
  member_code: 'KSD-01-M001',
  full_name: 'Test Member',
  phone: '9000000000',
  taluk_id: talukId,
  taluk_name: 'Kasargod',
  joined_on: '2026-01-01',
  version: 1,
  profile_version: 1,
  membership_type: 'REGULAR',
  account_status: 'ACTIVE',
  pending_amount: 200,
  permanent_account_id: null,
  permanent_target: 0,
  permanent_collected: 0,
  permanent_verified: 0,
  obligations: [{ id: obligationId, case_id: '00000000-0000-4000-8000-000000000504', label: 'Test death case', available_amount: 200 }],
}

async function mockWorkspace(page: Page, profile: typeof agentProfile | typeof adminProfile) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/session')
      ? { profile }
      : path.endsWith('/workspace')
        ? {
            profile,
            cases: [],
            members: profile.role === 'ADMIN' ? [member] : [],
            dues: [],
            collections: [collection],
            deposits: profile.role === 'ADMIN' ? [handover] : [],
            taluks: profile.role === 'ADMIN' ? [{ id: talukId, code: 'KSD-01', name: 'Kasargod', district: 'Kasargod', is_active: true, version: 1 }] : [],
            agents: profile.role === 'ADMIN' ? [{ ...agentProfile, account_status: 'ACTIVE', taluk_id: talukId, taluk_name: 'Kasargod', version: 1 }] : [],
            bank_accounts: [],
            notifications: [],
            case_whatsapp_tracking: [],
          }
        : {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) })
  })
}

test('agent payments are view-only', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockWorkspace(page, agentProfile)
  await page.goto('/agent/handovers')

  await expect(page.getByText('View-only access')).toHaveCount(0)
  await expect(page.getByText('Payment records')).toBeVisible()
  await expect(page.getByText('Test Member')).toBeVisible()
  await expect(page.getByRole('button', { name: /Record payment/i })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /New handover/i })).toHaveCount(0)
  const dimensions = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

test('administrator records and verifies a collection batch', async ({ page }) => {
  let submitted: Record<string, any> | undefined
  await page.setViewportSize({ width: 390, height: 844 })
  await mockWorkspace(page, adminProfile)
  await page.route('**/api/v1/admin/collection-batches', async route => {
    submitted = route.request().postDataJSON()
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ data: { id: 'batch-1' } }) })
  })
  await page.goto('/admin/handovers')

  await page.getByRole('button', { name: 'Record collection batch' }).click()
  await expect(page.getByRole('heading', { name: 'Record collection batch' })).toBeVisible()
  const dimensions = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
  await page.locator('.admin-collection-select input[type="checkbox"]').check()
  await expect(page.getByText('Amount received and verified')).toBeVisible()
  await page.getByRole('button', { name: 'Record INR 200' }).click()

  await expect.poll(() => submitted).toBeTruthy()
  expect(submitted!.agent_profile_id).toBe(agentProfile.id)
  expect(submitted!.declared_amount).toBe(200)
  expect(submitted!.entries).toHaveLength(1)
  expect(submitted!.entries[0].case_obligation_id).toBe(obligationId)
})

test('administrator sees handover details and receipt action', async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 707 })
  await mockWorkspace(page, adminProfile)
  await page.goto('/admin/handovers')

  await page.locator('.deposit-row').filter({ hasText: 'Test Agent' }).click()
  await expect(page.getByText('Amount handed over')).toBeVisible()
  await expect(page.getByText('Cash counted and handed over')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Confirm receipt' })).toBeEnabled()
  await expect(page.getByText('Destination bank')).toHaveCount(0)
})
