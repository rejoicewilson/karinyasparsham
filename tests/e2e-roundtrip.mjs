import { chromium } from 'playwright-core'
import assert from 'node:assert/strict'

const baseURL = 'http://127.0.0.1:5174'
const executablePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

const profiles = {
  admin: { id: 'p-admin', login_id: 'admin', full_name: 'System Administrator', role: 'ADMIN' },
  agent: { id: 'p-agent', login_id: 'thomas', full_name: 'Thomas', role: 'AGENT', taluk_name: 'Kuttanadu', bank: { bank_name: 'Test Bank', branch_name: 'Main', last4: '1234', ifsc_code: 'TEST0123456' } },
  member: { id: 'p-member', login_id: 'member2', full_name: 'Member Two', role: 'MEMBER', taluk_name: 'Kuttanadu', member_code: 'MEMBER2', agent: { id: 'p-agent', full_name: 'Thomas', phone: '9447000000' } },
}

const workspace = role => ({
  profile: profiles[role],
  cases: [{ id: 'case-1', case_number: 'DC-202608-001', deceased_name: 'James', taluk_name: 'Kuttanadu', death_date: '2026-08-11', created_at: '2026-08-11T08:00:00Z', contribution_amount: 1000, collected_amount: 500, verified_amount: 250, required_amount: 3000, status: 'OPEN', details: 'Test case', taluk_progress: [{ id: 'taluk-1', name: 'Kuttanadu', required: 3000, collected: 500, verified: 250 }] }],
  members: [{ id: 'member-1', member_code: 'MEMBER2', full_name: 'Member Two', phone: '9447000001', taluk_name: 'Kuttanadu', taluk_id: 'taluk-1', joined_on: '2026-01-01', version: 1, profile_version: 1, membership_type: 'REGULAR', pending_amount: 500, permanent_verified: 1000, permanent_collected: 5000, permanent_target: 15000, permanent_account_id: 'perm-1', account_status: 'ACTIVE', obligations: [{ id: 'obl-1', case_id: 'case-1', label: 'DC-202608-001', available_amount: 500 }] }],
  dues: [{ case_id: 'case-1', obligation_id: 'obl-1', label: 'James', case_number: 'DC-202608-001', required_amount: 1000, collected_amount: 500, verified_amount: 250 }],
  collections: [{ id: 'collection-1', receipt_number: 'RC-001', member_id: 'member-1', member_name: 'Member Two', case_id: 'case-1', label: 'DC-202608-001', collection_type: 'DEATH_CONTRIBUTION', amount: 500, method: 'CASH', collected_at: '2026-08-12T08:00:00Z', status: 'RECORDED', collector_name: 'Thomas' }],
  deposits: [
    { id: 'deposit-draft', deposit_number: 'DEP-DRAFT', agent_name: 'Thomas', taluk_name: 'Kuttanadu', bank_name: 'Test Bank', bank_last4: '1234', calculated_total: 500, declared_deposit_amount: 500, created_at: '2026-08-13T08:00:00Z', status: 'DRAFT', collection_ids: ['collection-1'], bank_reference: 'REF-DRAFT', version: 1 },
    { id: 'deposit-submitted', deposit_number: 'DEP-SUB', agent_name: 'Thomas', taluk_name: 'Kuttanadu', bank_name: 'Test Bank', bank_last4: '1234', calculated_total: 500, declared_deposit_amount: 500, submitted_at: '2026-08-13T09:00:00Z', status: 'SUBMITTED', collection_ids: ['collection-1'], bank_reference: 'REF-SUB', version: 1 },
    { id: 'deposit-approved', deposit_number: 'DEP-OK', agent_name: 'Thomas', taluk_name: 'Kuttanadu', bank_name: 'Test Bank', bank_last4: '1234', calculated_total: 500, declared_deposit_amount: 500, submitted_at: '2026-08-13T10:00:00Z', status: 'APPROVED', collection_ids: ['collection-1'], bank_reference: 'REF-OK', version: 2 },
    { id: 'deposit-rejected', deposit_number: 'DEP-NO', agent_name: 'Thomas', taluk_name: 'Kuttanadu', bank_name: 'Test Bank', bank_last4: '1234', calculated_total: 500, declared_deposit_amount: 500, submitted_at: '2026-08-13T11:00:00Z', status: 'REJECTED', collection_ids: ['collection-1'], bank_reference: 'REF-NO', rejection_reason: 'Test', version: 2 },
  ],
  taluks: [{ id: 'taluk-1', code: 'KUT', name: 'Kuttanadu', district: 'Alappuzha', is_active: true, version: 1, agent_profile_id: 'p-agent', agent_name: 'Thomas', bank_account_id: 'bank-1', bank_name: 'Test Bank', bank_last4: '1234', member_count: 1 }],
  agents: [{ id: 'p-agent', login_id: 'thomas', full_name: 'Thomas', phone: '9447000000', account_status: 'ACTIVE', version: 1, taluk_id: 'taluk-1', taluk_name: 'Kuttanadu' }],
  bank_accounts: [{ id: 'bank-1', taluk_id: 'taluk-1', agent_profile_id: 'p-agent', bank_name: 'Test Bank', last4: '1234' }],
  notifications: [{ id: 'notice-1', title: 'Deposit update', body: 'Deposit reviewed.', created_at: '2026-08-14T08:00:00Z', read: false, type: 'DEPOSIT_VERIFIED' }],
})

const clickNav = async (page, label) => {
  const bottom = page.locator('.bottom-nav button').filter({ hasText: label })
  if (await bottom.count()) return bottom.click()
  const sidebar = page.locator('.sidebar nav button').filter({ hasText: label })
  const box = await sidebar.boundingBox()
  if (!box || box.x < 0) await page.locator('.menu-btn').click()
  return sidebar.click()
}
const expectVisible = async (page, text) => {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible' })
}

async function testRole(browser, role, viewport) {
  const context = await browser.newContext({ acceptDownloads: true, serviceWorkers: 'block', viewport })
  const page = await context.newPage()
  const errors = []
  let loggedIn = false
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('Failed to load resource')) errors.push(message.text()) })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/session')) return route.fulfill({ status: loggedIn ? 200 : 401, contentType: 'application/json', body: JSON.stringify(loggedIn ? { data: { profile: profiles[role] } } : { error: { message: 'Unauthorized' } }) })
    if (path.endsWith('/auth/refresh')) return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: { message: 'Unauthorized' } }) })
    if (path.endsWith('/auth/login')) { loggedIn = true; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { profile: profiles[role] } }) }) }
    if (path.endsWith('/workspace')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: workspace(role) }) })
    if (path.endsWith('/death-cases/preview')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { next_sequence: 1, default_amount: 1000 } }) })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { id: 'test-id', version: 2, object_path: 'cases/test.webp', profile: profiles[role] } }) })
  })

  await page.goto(baseURL)
  await page.getByLabel('Login ID').fill(profiles[role].login_id)
  await page.getByPlaceholder('Enter your password').fill('TestPassword123!')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expectVisible(page, role === 'admin' ? 'Administration overview' : role === 'agent' ? 'Assigned members' : 'Amount to give agent')

  if (role === 'admin') {
    await page.getByRole('button', { name: 'New death case' }).click()
    await expectVisible(page, 'Create death case')
    await page.locator('.modal header .icon-btn').click()
    await clickNav(page, 'Death cases')
    await page.getByPlaceholder('Search case number or member').fill('missing')
    await expectVisible(page, 'No cases found')
    await page.getByPlaceholder('Search case number or member').fill('James')
    await page.getByText('James', { exact: true }).click()
    await expectVisible(page, 'Required total')
    await clickNav(page, 'Deposit review')
    await page.getByText('DEP-SUB', { exact: true }).click()
    await page.getByRole('button', { name: 'Approve deposit' }).click()
    const approvedWhatsapp = page.getByRole('link', { name: 'Send WhatsApp message to Member Two' })
    await approvedWhatsapp.waitFor({ state: 'visible' })
    assert.match(new URL(await approvedWhatsapp.getAttribute('href')).searchParams.get('text') || '', /Deposit: DEP-SUB/)
    await page.getByRole('button', { name: /^Approved \(/ }).click()
    await expectVisible(page, 'DEP-OK')
    await page.getByText('DEP-OK', { exact: true }).click()
    const whatsapp = page.getByRole('link', { name: 'Send WhatsApp message to Member Two' })
    await whatsapp.waitFor({ state: 'visible' })
    const whatsappUrl = new URL(await whatsapp.getAttribute('href'))
    assert.equal(whatsappUrl.hostname, 'wa.me')
    assert.equal(whatsappUrl.pathname, '/919447000001')
    const whatsappMessage = whatsappUrl.searchParams.get('text') || ''
    assert.match(whatsappMessage, /₹500/)
    assert.match(whatsappMessage, /Bank: Test Bank/)
    assert.match(whatsappMessage, /Deposit: DEP-OK/)
    assert.match(whatsappMessage, /Reference: REF-OK/)
    await page.getByRole('button', { name: /Rejected/ }).click()
    await expectVisible(page, 'DEP-NO')
    await clickNav(page, 'Members')
    await page.getByRole('button', { name: /Permanent/ }).click()
    await expectVisible(page, 'No members found')
    await page.getByRole('button', { name: /Active/ }).click()
    await expectVisible(page, 'Member Two')
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await expectVisible(page, 'Edit member')
    await page.locator('.modal header .icon-btn').click()
    await clickNav(page, 'Taluks & banks')
    await page.getByPlaceholder('Search taluk or agent').fill('KUT')
    await expectVisible(page, 'Kuttanadu Taluk')
    await clickNav(page, 'Reports')
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /Outstanding dues/ }).click()
    await download
    await clickNav(page, 'Settings')
    await expectVisible(page, 'Runtime settings')
  }

  if (role === 'agent') {
    await clickNav(page, 'Collect')
    await page.getByRole('button', { name: 'Partial' }).click()
    await expectVisible(page, 'Member Two')
    await clickNav(page, 'Deposits')
    await page.getByRole('button', { name: 'Approved' }).click()
    await expectVisible(page, 'DEP-OK')
    await page.getByRole('button', { name: 'Draft' }).click()
    await page.getByRole('button', { name: 'Submit', exact: true }).click()
    await clickNav(page, 'Members')
    await page.getByText('Member Two', { exact: true }).click()
    await expectVisible(page, 'Permanent collected')
    await clickNav(page, 'Home')
    await page.getByText('James', { exact: true }).click()
    await expectVisible(page, 'Required total')
    await clickNav(page, 'Account')
    await page.getByRole('button', { name: /Change password/ }).click()
    await expectVisible(page, 'Update password')
  }

  if (role === 'member') {
    await page.getByRole('button', { name: /View dues/ }).click()
    await page.getByRole('button', { name: /All obligations/ }).click()
    await expectVisible(page, 'DC-202608-001')
    await clickNav(page, 'Cases')
    await page.getByText('James', { exact: true }).click()
    await expectVisible(page, 'Your contribution')
    await clickNav(page, 'Payments')
    await page.getByRole('button', { name: 'Awaiting' }).click()
    await expectVisible(page, 'RC-001')
    await clickNav(page, 'Account')
    await page.getByRole('button', { name: /Change password/ }).click()
    await expectVisible(page, 'Update password')
  }

  if (errors.length) throw new Error(`${role} browser errors: ${errors.join(' | ')}`)
  await context.close()
}

const browser = await chromium.launch({ executablePath, headless: true })
try {
  for (const viewport of [{ width: 1365, height: 768 }, { width: 390, height: 844 }]) {
    for (const role of ['admin', 'agent', 'member']) await testRole(browser, role, viewport)
  }
  console.log('E2E round trip passed: admin, agent, member at desktop and mobile viewports')
} finally {
  await browser.close()
}
