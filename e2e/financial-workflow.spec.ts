import path from 'node:path'
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from '@playwright/test'

type RecordData = Record<string, any>

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:5174'
const adminLoginId = process.env.E2E_ADMIN_LOGIN_ID || ''
const adminPassword = process.env.E2E_ADMIN_PASSWORD || ''
const mutationsEnabled = process.env.E2E_ALLOW_MUTATIONS === 'true'

function assertSafeTarget(target: string) {
  const hostname = new URL(target).hostname.toLowerCase()
  const safe = ['localhost', '127.0.0.1'].includes(hostname)
    || ['e2e', 'test', 'staging', 'preview'].some(marker => hostname.includes(marker))
  if (!safe) {
    throw new Error(`Refusing to mutate ${hostname}. Use a dedicated test/staging deployment.`)
  }
}

async function responseData<T = RecordData>(response: APIResponse, operation: string): Promise<T> {
  if (!response.ok()) {
    throw new Error(`${operation} failed (${response.status()}): ${await response.text()}`)
  }
  return (await response.json()).data as T
}

async function apiLogin(api: APIRequestContext, loginId: string, password: string) {
  await responseData(await api.post('/api/v1/auth/login', {
    data: { login_id: loginId, password },
  }), `Login for ${loginId}`)
}

async function uiLogin(
  page: Page,
  loginId: string,
  password: string,
  role: 'admin' | 'agent' | 'member',
  replacementPassword?: string,
) {
  await page.goto('/')
  await page.getByLabel('Login ID').fill(loginId)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: /^Sign in/ }).click()
  if (replacementPassword) {
    await expect(page.getByRole('heading', { name: 'Create a new password' })).toBeVisible()
    await page.getByLabel('New password').fill(replacementPassword)
    await page.getByLabel('Confirm password').fill(replacementPassword)
    await page.getByRole('button', { name: 'Update password' }).click()
  }
  await expect(page).toHaveURL(new RegExp(`/${role}/dashboard$`))
}

async function uiLogout(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
}

async function deactivateTestConfiguration(
  api: APIRequestContext,
  taluk: RecordData,
  agent: RecordData,
  memberIds: string[],
) {
  const workspace = await responseData<RecordData>(
    await api.get('/api/v1/workspace'), 'Load cleanup workspace')

  for (const memberId of memberIds.filter(Boolean)) {
    const profile = workspace.members.find((item: RecordData) => String(item.id) === memberId)
    if (!profile || String(profile.account_status) !== 'ACTIVE') continue
    await responseData(await api.patch(`/api/v1/admin/members/${memberId}`, {
      data: {
        expected_version: Number(profile.version),
        profile_expected_version: Number(profile.profile_version),
        member_code: String(profile.member_code),
        full_name: String(profile.full_name),
        phone: profile.phone || null,
        taluk_id: String(profile.taluk_id),
        joined_on: String(profile.joined_on),
        account_status: 'INACTIVE',
        reason: 'Automated end-to-end test cleanup',
      },
    }), `Deactivate test member ${profile.member_code}`)
  }

  const agentProfile = workspace.agents.find((item: RecordData) => String(item.id) === agent.id)
  if (agentProfile && String(agentProfile.account_status) === 'ACTIVE') {
    await responseData(await api.patch(`/api/v1/admin/agents/${agent.id}`, {
      data: {
        expected_version: Number(agentProfile.version),
        full_name: String(agentProfile.full_name),
        phone: agentProfile.phone || null,
        account_status: 'INACTIVE',
        taluk_id: null,
        reason: 'Automated end-to-end test cleanup',
      },
    }), 'Deactivate test agent')
  }

  const talukRecord = workspace.taluks.find((item: RecordData) => String(item.id) === taluk.id)
  if (talukRecord?.is_active) {
    await responseData(await api.patch(`/api/v1/admin/taluks/${taluk.id}`, {
      data: {
        expected_version: Number(talukRecord.version),
        code: String(talukRecord.code),
        name: String(talukRecord.name),
        district: talukRecord.district || null,
        is_active: false,
        reason: 'Automated end-to-end test cleanup',
      },
    }), 'Deactivate test taluk')
  }
}

test.describe('financial collection workflow', () => {
  test.skip(!mutationsEnabled || !adminLoginId || !adminPassword,
    'Set E2E_ALLOW_MUTATIONS=true, E2E_ADMIN_LOGIN_ID, and E2E_ADMIN_PASSWORD.')

  test('admin publishes case, agent hands over collection, admin confirms receipt, member balance updates', async ({ page }, testInfo) => {
    assertSafeTarget(baseURL)

    const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
    const today = new Date().toISOString().slice(0, 10)
    const contribution = 100
    const agent = {
      id: '', loginId: `e2e.agent.${suffix}`, name: `E2E Agent ${suffix}`,
      phone: '9000000001', temporaryPassword: `TempA!${suffix}`,
      password: `AgentA!${suffix}`,
    }
    const deceased = {
      id: '', loginId: `e2e.deceased.${suffix}`, code: `E2ED${suffix}`,
      name: `E2E Deceased ${suffix}`, phone: '9000000002',
      temporaryPassword: `TempD!${suffix}`,
    }
    const member = {
      id: '', loginId: `e2e.member.${suffix}`, code: `E2EM${suffix}`,
      name: `E2E Member ${suffix}`, phone: '9000000003',
      temporaryPassword: `TempM!${suffix}`, password: `MemberM!${suffix}`,
    }
    const taluk = {
      id: '', code: `E2E${suffix}`.slice(0, 20), name: `E2E Taluk ${suffix}`,
      district: 'Automated Test',
    }
    let caseId = ''

    const adminApi = await request.newContext({ baseURL })
    try {
      await test.step('provision isolated test records', async () => {
        await apiLogin(adminApi, adminLoginId, adminPassword)
        const createdTaluk = await responseData(await adminApi.post('/api/v1/admin/taluks', {
          data: { code: taluk.code, name: taluk.name, district: taluk.district },
        }), 'Create taluk')
        taluk.id = String(createdTaluk.id)

        const createdAgent = await responseData(await adminApi.post('/api/v1/admin/agents', {
          data: {
            login_id: agent.loginId,
            temporary_password: agent.temporaryPassword,
            full_name: agent.name,
            phone: agent.phone,
            taluk_id: taluk.id,
          },
        }), 'Create agent')
        agent.id = String(createdAgent.id)

        await responseData(await adminApi.post('/api/v1/admin/bank-accounts', {
          data: {
            taluk_id: taluk.id,
            agent_profile_id: agent.id,
            bank_name: 'E2E Test Bank',
            branch_name: 'Automation Branch',
            account_holder_name: agent.name,
            account_number: `123456${Date.now().toString().slice(-6)}`,
            ifsc_code: 'TEST0123456',
          },
        }), 'Create bank account')

        for (const profile of [deceased, member]) {
          const created = await responseData(await adminApi.post('/api/v1/admin/members', {
            data: {
              login_id: profile.loginId,
              temporary_password: profile.temporaryPassword,
              member_code: profile.code,
              full_name: profile.name,
              phone: profile.phone,
              taluk_id: taluk.id,
              joined_on: today,
            },
          }), `Create member ${profile.code}`)
          profile.id = String(created.id)
        }
      })

      await test.step('admin creates and publishes a death case', async () => {
        await uiLogin(page, adminLoginId, adminPassword, 'admin')
        await page.goto('/admin/cases')
        await page.getByRole('button', { name: 'Create case' }).click()
        await page.getByLabel('Deceased member').selectOption(deceased.id)
        await page.getByLabel('Date of death').fill(today)
        await page.getByLabel('Case details').fill(`Automated end-to-end case ${suffix}`)
        await page.getByLabel('Member photo').setInputFiles(path.resolve('public/logo.png'))
        await page.getByRole('checkbox').check()
        await page.getByLabel('Contribution amount').fill(String(contribution))
        await page.getByLabel('Override reason').fill('Automated end-to-end verification')

        const published = page.waitForResponse(response =>
          response.request().method() === 'POST'
          && new URL(response.url()).pathname.endsWith('/api/v1/admin/death-cases'))
        await page.getByRole('button', { name: 'Publish case' }).click()
        caseId = String((await responseData(await published, 'Publish death case')).id)
        await expect(page.getByText('Death case published. WhatsApp messages are ready.')).toBeVisible()
        await expect(page.getByRole('heading', { name: /Notify members on WhatsApp/ })).toBeVisible()
        await expect(page.getByRole('link', {
          name: `Open WhatsApp message for ${member.name}`,
        })).toBeVisible()
        await page.getByRole('button', { name: `Mark WhatsApp message sent to ${member.name}` }).click()
        await expect(page.getByRole('button', { name: `Undo sent status for ${member.name}` })).toBeVisible()
        await uiLogout(page)
      })

      await test.step('agent records the member collection and submits a handover', async () => {
        await uiLogin(page, agent.loginId, agent.temporaryPassword, 'agent', agent.password)
        await page.goto('/agent/collect')
        await page.getByRole('button', { name: 'Record payment' }).click()
        await page.getByLabel('Member').selectOption(member.id)
        await page.getByLabel('Collection for').selectOption(caseId)
        await page.getByLabel('Amount').fill(String(contribution))
        await page.getByLabel('Method').selectOption('Cash')
        await page.getByRole('button', { name: /^Record / }).click()
        await expect(page.getByText(new RegExp(`collection recorded for ${member.name}`))).toBeVisible()

        await page.goto('/agent/handovers')
        await page.getByRole('button', { name: 'New handover' }).click()
        await page.getByLabel(/Handover note/).fill(`E2E-${suffix}`)
        await page.getByRole('button', { name: 'Submit handover' }).click()
        await expect(page.getByText('Handover submitted for administrator confirmation.')).toBeVisible()
        const adminWhatsApp = page.getByRole('link', { name: 'WhatsApp admin' })
        await expect(adminWhatsApp).toHaveAttribute('href', /wa\.me\/919447645196/)
        await page.getByRole('button', { name: 'Close', exact: true }).click()
        await uiLogout(page)
      })

      await test.step('admin confirms the submitted handover', async () => {
        await uiLogin(page, adminLoginId, adminPassword, 'admin')
        await page.goto('/admin/handovers')
        const depositRow = page.locator('.deposit-row').filter({ hasText: agent.name }).first()
        await expect(depositRow).toBeVisible()
        await depositRow.click()
        await page.getByRole('button', { name: 'Confirm receipt' }).click()
        await expect(page.getByText('Handover received. WhatsApp messages are ready for the agent and members.')).toBeVisible()
        await uiLogout(page)
      })

      await test.step('member sees the verified balance and the API ledger agrees', async () => {
        await uiLogin(page, member.loginId, member.temporaryPassword, 'member', member.password)
        const verifiedMetric = page.locator('.metric').filter({ hasText: 'Verified total' })
        await expect(verifiedMetric).toContainText('100')

        const workspace = await responseData<RecordData>(
          await page.request.get('/api/v1/workspace'), 'Load member workspace')
        const due = workspace.dues.find((item: RecordData) => String(item.case_id) === caseId)
        expect(due).toBeTruthy()
        expect(Number(due.required_amount)).toBe(contribution)
        expect(Number(due.collected_amount)).toBe(contribution)
        expect(Number(due.verified_amount)).toBe(contribution)
        expect(Number(due.amount_still_to_collect)).toBe(0)
      })
    } finally {
      try {
        if (taluk.id) {
          await apiLogin(adminApi, adminLoginId, adminPassword)
          await deactivateTestConfiguration(
            adminApi, taluk, agent, [deceased.id, member.id])
        }
      } catch (error) {
        await testInfo.attach('cleanup-error', {
          body: error instanceof Error ? error.stack || error.message : String(error),
          contentType: 'text/plain',
        })
      } finally {
        await adminApi.dispose()
      }
    }
  })
})
