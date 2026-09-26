import { expect, test, type Page } from '@playwright/test'


const profile = {
  id: '00000000-0000-4000-8000-000000000100',
  login_id: 'admin',
  full_name: 'System Administrator',
  role: 'ADMIN',
  must_change_password: false,
}

const members = [
  { id: '1', member_code: 'KSD-M001', ard_no: '2469002', full_name: 'Kasargod Active', phone: '9000000001', taluk_name: 'Kasargod', taluk_id: 'ksd', membership_type: 'REGULAR', account_status: 'ACTIVE' },
  { id: '2', member_code: 'KSD-M002', full_name: 'Kasargod Inactive', phone: '9000000002', taluk_name: 'Kasargod', taluk_id: 'ksd', membership_type: 'REGULAR', account_status: 'INACTIVE' },
  { id: '3', member_code: 'KSD-03-M001', full_name: 'Vellarikundu Active', phone: '9000000003', taluk_name: 'Vellarikundu', taluk_id: 'ksd-03', membership_type: 'REGULAR', account_status: 'ACTIVE' },
].map(item => ({
  ...item,
  joined_on: '2026-01-01',
  version: 1,
  profile_version: 1,
  pending_amount: 0,
  permanent_verified: 0,
  permanent_target: 15000,
  permanent_collected: 0,
  obligations: item.id === '1' ? [{
    id: 'obligation-1',
    case_id: 'case-1',
    case_number: 'HIST-001',
    label: 'Historical member',
    required_amount: 200,
    collected_amount: 100,
    verified_amount: 100,
    available_amount: 100,
  }] : [],
}))

const cases = [
  {
    id: 'case-1', case_number: 'HIST-001', deceased_name: 'Historical member', taluk_name: 'Kasargod',
    death_date: '2026-01-20', created_at: '2026-01-20T12:00:00Z', contribution_amount: 200,
    required_amount: 600, collected_amount: 300, verified_amount: 300, status: 'OPEN', details: 'Historical case',
    taluk_progress: [
      { id: 'ksd', name: 'Kasargod', required: 400, collected: 250, verified: 250 },
      { id: 'ksd-03', name: 'Vellarikundu', required: 200, collected: 50, verified: 50 },
    ],
  },
]

async function mockMembersWorkspace(page: Page) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/auth/session')
      ? { profile }
      : path.endsWith('/workspace')
        ? {
            profile,
            cases,
            members,
            dues: [],
            collections: [],
            deposits: [],
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

test('administrator filters members and counts by taluk on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMembersWorkspace(page)
  await page.goto('/admin/members')

  const talukBox = await page.getByLabel('Filter members by taluk').boundingBox()
  const addMemberBox = await page.getByRole('button', { name: 'Add member' }).boundingBox()
  expect(talukBox).not.toBeNull()
  expect(addMemberBox).not.toBeNull()
  expect(Math.abs(talukBox!.y - addMemberBox!.y)).toBeLessThanOrEqual(1)
  expect(Math.abs(talukBox!.height - addMemberBox!.height)).toBeLessThanOrEqual(1)

  await expect(page.getByRole('button', { name: 'Active (2)' })).toBeVisible()
  await page.getByPlaceholder('Search name, member code, ARD or phone').fill('2469002')
  await expect(page.getByText('Kasargod Active')).toBeVisible()
  await expect(page.getByText('Vellarikundu Active')).toHaveCount(0)
  await page.getByPlaceholder('Search name, member code, ARD or phone').fill('')
  await page.getByLabel('Filter members by taluk').selectOption('Vellarikundu')
  const summary = page.getByRole('region', { name: 'Vellarikundu financial summary' })
  await expect(summary.getByText('Death cases')).toBeVisible()
  await expect(summary.getByText('1', { exact: true })).toBeVisible()
  await expect(summary.getByText('50', { exact: true })).toBeVisible()
  await expect(summary.getByText('150', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Active (1)' })).toBeVisible()
  await expect(page.getByText('Vellarikundu Active')).toBeVisible()
  await expect(page.getByText('Kasargod Active')).toHaveCount(0)

  await page.getByLabel('Filter members by taluk').selectOption('Kasargod')
  await page.getByRole('button', { name: 'Inactive (1)' }).click()
  await expect(page.getByText('Kasargod Inactive')).toBeVisible()

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

test('administrator opens a member case-by-case payment ledger', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await mockMembersWorkspace(page)
  await page.goto('/admin/members')

  await page.getByText('Kasargod Active', { exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/members\/1$/)
  await expect(page.getByRole('heading', { name: 'Case-by-case payment ledger' })).toBeVisible()
  await expect(page.getByText('HIST-001', { exact: true })).toBeVisible()
  await expect(page.getByText('Historical member', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pending (1)' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Verified (0)' })).toBeVisible()

  const amounts = page.locator('.member-case-amounts')
  await expect(amounts).toContainText('Required')
  await expect(amounts).toContainText('Collected')
  await expect(amounts).toContainText('Verified')
  await expect(amounts).toContainText('Pending')

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
  await page.screenshot({ path: 'test-results/admin-member-ledger-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  const mobileDimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(mobileDimensions.scrollWidth).toBeLessThanOrEqual(mobileDimensions.clientWidth)
  await page.screenshot({ path: 'test-results/admin-member-ledger-mobile.png', fullPage: true })
})
