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

async function mockWorkspace(page: Page, profile: typeof agentProfile | typeof adminProfile) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/session')
      ? { profile }
      : path.endsWith('/workspace')
        ? {
            profile,
            cases: [],
            members: [],
            dues: [],
            collections: [collection],
            deposits: profile.role === 'ADMIN' ? [handover] : [],
            taluks: [],
            agents: [],
            bank_accounts: [],
            notifications: [],
            case_whatsapp_tracking: [],
          }
        : {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) })
  })
}

test('agent can prepare a handover without a bank account', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockWorkspace(page, agentProfile)
  await page.goto('/agent/handovers')

  await expect(page.getByRole('heading', { name: 'Collection handovers' })).toBeVisible()
  await page.getByRole('button', { name: 'New handover' }).click()
  await expect(page.getByRole('heading', { name: 'Prepare collection handover' })).toBeVisible()
  await expect(page.getByLabel('Amount handed over')).toHaveValue('500')
  await expect(page.getByLabel(/Handover note/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit handover' })).toBeEnabled()
  const dimensions = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
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
