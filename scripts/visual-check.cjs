const { chromium } = require('playwright-core')

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  })

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await mobile.goto('http://127.0.0.1:5174', { waitUntil: 'networkidle' })
  console.log('LOGIN', await dimensions(mobile))
  await mobile.screenshot({ path: 'playwright-login-mobile.png', fullPage: true })
  await mobile.getByRole('button', { name: 'Member' }).click()
  await mobile.waitForTimeout(500)
  console.log('MEMBER', await dimensions(mobile))
  await mobile.screenshot({ path: 'playwright-member-mobile.png', fullPage: true })

  const desktop = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  await desktop.goto('http://127.0.0.1:5174', { waitUntil: 'networkidle' })
  await desktop.getByRole('button', { name: 'Admin' }).click()
  await desktop.waitForTimeout(500)
  console.log('ADMIN', await dimensions(desktop))
  await desktop.screenshot({ path: 'playwright-admin-desktop.png', fullPage: true })

  await browser.close()
}

function dimensions(page) {
  return page.evaluate(() => ({
    path: location.pathname,
    viewportWidth: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    overflow: document.documentElement.scrollWidth > innerWidth,
  }))
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
