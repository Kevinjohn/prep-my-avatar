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
  const datasetName = `E2E ${suffix} Avatar`;
  await openDatasets(page);
  expect(await accessibilityViolations(page)).toEqual([]);

  if (!await page.getByLabel('Character name').isVisible()) {
    await page.getByRole('button', { name: '+ New dataset', exact: true }).click();
  }
  await page.getByLabel('Character name').fill(datasetName);
  await page.getByLabel(/^Trigger word/).fill(`zchar_e2e_${suffix.toLowerCase()}_avatar`);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('heading', { name: datasetName, level: 1 })).toBeVisible();
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
});

test('primary pages fit the viewport without horizontal overflow', async ({ page }) => {
  await openDatasets(page);
  for (const route of ['datasets', 'settings', 'guide', 'help']) {
    await page.goto(`/#/${route}`);
    await expect.poll(() => page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
    expect(await accessibilityViolations(page)).toEqual([]);
  }
});
