import { expect, test } from '@playwright/test';
import axe from 'axe-core';

async function openDatasets(page) {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  await expect(page.getByRole('heading', { name: 'Datasets', level: 1 })).toBeVisible();
}

async function accessibilityViolations(page) {
  await page.addScriptTag({ content: axe.source });
  const result = await page.evaluate(async () => window.axe.run(document, {
    resultTypes: ['violations'],
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
  }));
  return result.violations;
}

test('dataset flow, destructive dialog focus, and accessibility', async ({ page }, testInfo) => {
  const suffix = testInfo.project.name === 'mobile' ? 'Mobile' : 'Desktop';
  const datasetName = `E2E ${suffix} Retry ${testInfo.retry} Avatar`;
  await openDatasets(page);
  expect(await accessibilityViolations(page)).toEqual([]);

  if (!await page.getByLabel('Character name').isVisible()) {
    await page.getByRole('button', { name: '+ New dataset', exact: true }).click();
  }
  await page.getByLabel('Character name').fill(datasetName);
  await page.getByLabel(/^Trigger word/).fill(`zchar_e2e_${suffix.toLowerCase()}_avatar`);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('heading', { name: datasetName, level: 1 })).toBeVisible();
  await page.getByTitle('More dataset actions — edit settings, body fidelity').click();
  const editSettings = page.getByRole('button', { name: /Edit settings/ });
  await expect(editSettings).toBeVisible();
  const menuBackground = await editSettings.evaluate(
    (button) => getComputedStyle(button.parentElement).backgroundColor,
  );
  expect(menuBackground).not.toBe('rgba(0, 0, 0, 0)');
  await page.getByRole('button', { name: '← Datasets' }).click();

  const deleteButton = page.getByRole('button', { name: `Move the dataset ${datasetName} to trash` });
  await deleteButton.click();
  const dialog = page.getByRole('alertdialog', { name: `Move “${datasetName}” to trash?` });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  expect(await accessibilityViolations(page)).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
  await expect(deleteButton).toBeFocused();
  await deleteButton.click();
  await page.getByRole('button', { name: 'Move to trash', exact: true }).click();
  await expect(page.getByRole('heading', { name: datasetName, level: 1 })).toHaveCount(0);
});

test('direct Studio route renders its capability-gated destination', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/studio');
  await expect(page.getByRole('heading', { name: 'Test Studio', level: 1 })).toBeVisible();
  await expect(page.getByText('Test Studio requires ComfyUI')).toBeVisible();
});

test('dirty settings block SPA navigation until the user confirms', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  await page.evaluate(() => { window.location.hash = '/settings/server'; });
  await expect(page.getByRole('heading', { name: 'Server', level: 1 })).toBeVisible();
  const port = page.getByLabel('Port');
  const original = Number(await port.inputValue());
  await port.fill(String(original === 65535 ? 65534 : original + 1));

  page.once('dialog', (dialog) => dialog.dismiss());
  await page.goBack();
  await expect(page).toHaveURL(/#\/settings\/server$/);
  await expect(port).toHaveValue(String(original === 65535 ? 65534 : original + 1));

  const mobileMenu = page.getByRole('button', { name: 'Open navigation menu' });
  if (await mobileMenu.isVisible()) await mobileMenu.click();
  const datasets = page.locator('nav:visible').getByRole('link', { name: 'Datasets', exact: true });
  page.once('dialog', (dialog) => dialog.dismiss());
  await datasets.click();
  await expect(page).toHaveURL(/#\/settings\/server$/);
  await expect(port).toHaveValue(String(original === 65535 ? 65534 : original + 1));

  page.once('dialog', (dialog) => dialog.accept());
  await datasets.click();
  await expect(page).toHaveURL(/#\/datasets$/);
});

test('lazy top-level routes render without page errors', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (const [route, heading] of [
    ['cloud', 'Training runs'],
    ['setup', /Welcome to Prep My Avatar|You're all set|Setup/],
    ['studio', 'Test Studio'],
  ]) {
    await page.goto(`/#/${route}`);
    await expect(page.getByRole('heading', { name: heading, level: 1 }).first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test('primary pages fit the viewport without horizontal overflow', async ({ page }) => {
  await openDatasets(page);
  const mobileMenu = page.getByRole('button', { name: 'Open navigation menu' });
  if (await mobileMenu.isVisible()) await mobileMenu.click();
  await page.locator('nav:visible').getByRole('link', { name: 'Help', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Getting help', level: 1 })).toBeVisible();
  const routes = [
    ['datasets', 'Datasets'],
    ['settings', 'Overview'],
    ['guide', 'Getting started'],
    ['help', 'Getting help'],
  ];
  for (const [route, heading] of routes) {
    await page.goto(`/#/${route}`);
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible();
    if (route === 'guide') {
      await expect(page.getByRole('navigation', { name: 'Guide chapters' })
        .getByRole('link', { name: /Getting help/ })).toHaveCount(0);
    }
    if (route === 'help') {
      await expect(page.getByRole('link', { name: 'Prep My Avatar issues' }))
        .toHaveAttribute('href', 'https://github.com/Kevinjohn/prep-my-avatar/issues');
      await expect(page.getByRole('link', { name: 'Discord' }))
        .toHaveAttribute('href', 'https://discord.gg/j6hnJBFtXE');
    }
    await expect.poll(() => page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
    expect(await accessibilityViolations(page)).toEqual([]);
  }
});
