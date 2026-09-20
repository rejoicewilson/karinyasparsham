import { expect, test, type Page } from '@playwright/test'


const taluks = [
  'Alathur', 'Aluva', 'Ambalapuzha', 'Chalakudy',
  'Changanassery', 'Chavakkad', 'Chengannur', 'Hosdurg',
].map((name, index) => ({
  id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  code: `TLK-${index + 1}`,
  name,
  district: 'Kerala',
  is_active: true,
  version: 1,
  agent_profile_id: null,
  agent_name: null,
  bank_account_id: null,
  bank_name: null,
  member_count: 0,
}))

const profile = {
  id: '00000000-0000-4000-8000-000000000100',
  login_id: 'admin',
  full_name: 'System Administrator',
  role: 'ADMIN',
  must_change_password: false,
}

const agent = {
  id: '00000000-0000-4000-8000-000000000200',
  login_id: 'agent-test',
  full_name: 'Test Agent',
  phone: '9447000000',
  account_status: 'ACTIVE',
  version: 1,
  taluk_id: taluks[0].id,
  taluk_name: taluks[0].name,
}

async function mockAdminWorkspace(page: Page) {
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
            collections: [],
            deposits: [],
            taluks,
            agents: [agent],
            bank_accounts: [],
            notifications: [],
            case_whatsapp_tracking: [],
          }
        : {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) })
  })
}

test('Organization no longer exposes bank configuration', async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 707 })
  await mockAdminWorkspace(page)
  await page.goto('/admin/taluks')

  await expect(page.getByRole('button', { name: 'Taluk', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Bank', exact: true })).toHaveCount(0)
  await expect(page.getByText('Bank account', { exact: true })).toHaveCount(0)
  await expect(page.getByTitle('Replace bank account')).toHaveCount(0)
})

test('View all taluks opens the detailed taluk report', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockAdminWorkspace(page)
  await page.goto('/admin/dashboard')

  await page.getByRole('button', { name: 'View all 8 taluks' }).click()
  await expect(page).toHaveURL(/\/admin\/reports$/)
  await expect(page.getByRole('heading', { name: 'Taluk collection performance' })).toBeVisible()
  await expect(page.locator('.taluk-report-row')).toHaveCount(8)
  await expect(page.getByRole('button', { name: 'Export taluk report' })).toBeVisible()
  const dimensions = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

for (const viewport of [
  { name: 'windows-fullscreen', width: 1365, height: 707 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`Admin dashboard fits ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await mockAdminWorkspace(page)
    await page.goto('/admin/dashboard')
    await expect(page.getByRole('heading', { name: 'Administration overview' })).toBeVisible()

    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)

    const metrics = page.locator('.admin-metrics .metric')
    await expect(metrics).toHaveCount(4)
    const lastMetric = await metrics.last().boundingBox()
    expect(lastMetric).not.toBeNull()
    expect(lastMetric!.x + lastMetric!.width).toBeLessThanOrEqual(viewport.width)

    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}.png`),
      fullPage: true,
    })
  })
}
