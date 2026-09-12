# End-to-end financial workflow

This suite exercises the real browser, API, Supabase Auth, database, and private Storage flow:

1. Provision a unique taluk, agent, bank, deceased member, and contributing member.
2. Publish a death case as the administrator.
3. Record a collection and submit its handover as the assigned agent.
4. Confirm receipt of the handover as the administrator.
5. Sign in as the member and verify the required, collected, and verified ledger amounts.
6. Deactivate the generated member, agent, bank assignment, and taluk configuration.

## Safety

Run this only against a dedicated test Supabase project and test/staging frontend deployment. The test mutates financial records. It refuses hosts that do not contain `e2e`, `test`, `staging`, or `preview`, except `localhost` and `127.0.0.1`.

The dedicated project must have the migrations applied and an administrator account whose first-sign-in password change is already complete.

## Local command

In PowerShell:

```powershell
npm run test:e2e:install
$env:E2E_BASE_URL='https://your-e2e-deployment.vercel.app'
$env:E2E_ADMIN_LOGIN_ID='e2e-admin'
$env:E2E_ADMIN_PASSWORD='your-test-admin-password'
$env:E2E_ALLOW_MUTATIONS='true'
npm run test:e2e
```

Do not put the administrator password in a tracked file. For GitHub Actions, configure these values as secrets in an `e2e` environment and run the **Financial workflow E2E** action manually.
