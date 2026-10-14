import { expect, test, type Page } from '@playwright/test'

/**
 * The B5 journey, against the mock (src/mocks/): Se connecter → /authorize → /login?uid →
 * numero fiscal + password → consent → /callback → the portal with its tiles.
 * Mock credentials: src/mocks/data.ts.
 */
const NUMERO = '1234567890123' // Marie Dupont, agent
const PASSWORD = 'Authentint-dev-1!'

/** Every URL the browser asked for, so we can prove the numero fiscal never was in one. */
function recordUrls(page: Page): string[] {
  const urls: string[] = []
  page.on('request', (request) => urls.push(request.url()))
  page.on('framenavigated', (frame) => urls.push(frame.url()))
  return urls
}

test('se connecter, consentir, revenir au portail et voir ses tuiles', async ({ page }) => {
  const urls = recordUrls(page)
  const consoleLines: string[] = []
  page.on('console', (message) => consoleLines.push(message.text()))

  await page.goto('/')
  await page.getByRole('button', { name: 'Se connecter' }).click()

  // /authorize (mock) sent us to the step machine
  await expect(page).toHaveURL(/\/login\?uid=/)
  await page.getByLabel('Numéro fiscal').fill(NUMERO)
  await page.getByLabel('Mot de passe').fill(PASSWORD)
  await page.getByRole('button', { name: 'Se connecter' }).click()

  // The server answered prompt=consent
  await expect(page.getByRole('heading', { name: "Autoriser l'accès" })).toBeVisible()
  await expect(page.getByText('Consulter vos dossiers fiscaux')).toBeVisible()
  await page.getByRole('button', { name: 'Accepter' }).click()

  // /callback exchanged the code, then the portal
  await expect(page.getByRole('heading', { name: 'Bonjour, Marie Dupont' })).toBeVisible()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('tuile-impots')).toBeVisible()
  await expect(page.getByTestId('tuile-cadastre')).toBeVisible()

  // Defence in depth, checked in a real browser
  expect(urls.filter((url) => url.includes(NUMERO))).toEqual([])
  expect(consoleLines.filter((line) => line.includes(NUMERO) || line.includes(PASSWORD))).toEqual([])
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))
  expect(storage).not.toContain('eyJ') // no JWT in Web Storage
  expect(storage).not.toContain(NUMERO)

  // Se déconnecter → end-session (mock) → back to the logged-out portal
  await page.getByRole('button', { name: 'Se déconnecter' }).click()
  await expect(page.getByRole('heading', { name: "Bienvenue sur Authent'INT" })).toBeVisible()
})

test('un contribuable ne voit que la tuile Impôts', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByLabel('Numéro fiscal').fill('2345678901234') // Jean Martin, contribuable
  await page.getByLabel('Mot de passe').fill(PASSWORD)
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByRole('button', { name: 'Accepter' }).click()

  await expect(page.getByRole('heading', { name: 'Bonjour, Jean Martin' })).toBeVisible()
  await expect(page.getByTestId('tuile-impots')).toBeVisible()
  await expect(page.getByTestId('tuile-cadastre')).toHaveCount(0)
})

test("refuser le consentement revient à l'application avec un message",async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByLabel('Numéro fiscal').fill(NUMERO)
  await page.getByLabel('Mot de passe').fill(PASSWORD)
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByRole('button', { name: 'Refuser' }).click()

  await expect(page.getByRole('alert')).toContainText("Vous avez refusé l'accès")
  await expect(page).toHaveURL(/\/callback$/)
})

test('un mauvais mot de passe affiche le message en français', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await page.getByLabel('Numéro fiscal').fill(NUMERO)
  await page.getByLabel('Mot de passe').fill('pas-le-bon')
  await page.getByRole('button', { name: 'Se connecter' }).click()
  await expect(page.getByRole('alert')).toHaveText('Numéro fiscal ou mot de passe incorrect.')
})

test("le jeton d'activation disparaît de la barre d'adresse", async ({ page }) => {
  await page.goto('/activate?token=lien-de-test-valide')
  await expect(page.getByLabel('Mot de passe', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/activate$/)
  await page.getByLabel('Mot de passe', { exact: true }).fill('une phrase de passe assez longue')
  await page.getByLabel('Confirmez le mot de passe').fill('une phrase de passe assez longue')
  await page.getByRole('button', { name: 'Enregistrer le mot de passe' }).click()
  await expect(page.getByRole('status')).toContainText('Votre compte est activé.')
})
