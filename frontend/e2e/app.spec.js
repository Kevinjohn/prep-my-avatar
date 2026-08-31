import { expect, test } from '@playwright/test';
import axe from 'axe-core';

async function openDatasets(page) {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  await expect(page.getByRole('heading', { name: 'Datasets', level: 1 })).toBeVisible();
}

async function postJson(page, path, body) {
  return page.evaluate(async ({ requestPath, requestBody }) => {
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    const response = await fetch(requestPath, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': match ? decodeURIComponent(match[1]) : '',
      },
      body: JSON.stringify(requestBody),
    });
    return { status: response.status, body: await response.json() };
  }, { requestPath: path, requestBody: body });
}

async function importSolidImage(page, datasetId, filename, colour) {
  return page.evaluate(async ({ id, name, rgb }) => {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const context = canvas.getContext('2d');
    context.fillStyle = `rgb(${rgb.join(',')})`;
    context.fillRect(0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    const data = new FormData();
    data.append('files', blob, name);
    data.append('crop', '0');
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    data.append('csrf_token', match ? decodeURIComponent(match[1]) : '');
    const response = await fetch(`/api/dataset/${id}/import`, {
      method: 'POST', credentials: 'include', body: data,
    });
    return { status: response.status, body: await response.json() };
  }, { id: datasetId, name: filename, rgb: colour });
}

async function seedImportedDataset(page, name, imageCount = 1) {
  const created = await postJson(page, '/api/dataset/create', {
    name, trigger_word: `z_${name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}`,
  });
  expect(created.status).toBe(200);
  const datasetId = created.body.id;
  const imageIds = [];
  for (let index = 0; index < imageCount; index += 1) {
    const imported = await importSolidImage(
      page, datasetId, `fixture-${index}.png`,
      index % 2 ? [30, 160, 220] : [220, 90, 40],
    );
    expect(imported.status).toBe(200);
    expect(imported.body.imported).toBe(1);
  }
  const payload = await page.evaluate(async (id) => (
    fetch(`/api/dataset/${id}?include_images=1`).then((response) => response.json())
  ), datasetId);
  for (const image of payload.images) {
    imageIds.push(image.id);
    const kept = await postJson(page, `/api/dataset/image/${image.id}/status`, {
      status: 'keep',
    });
    expect(kept.status).toBe(200);
  }
  return { datasetId, imageIds };
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
  await expect(page.getByRole('heading', { name: 'Import photos', level: 1 })).toBeVisible();
  await expect(page.getByText(datasetName, { exact: true })).toBeVisible();
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
  await expect(page.getByText(datasetName, { exact: true })).toHaveCount(0);
});

test('dataset workflow uses one canonical page per guide step', async ({ page }, testInfo) => {
  await openDatasets(page);
  const { datasetId } = await seedImportedDataset(
    page, `Step flow ${testInfo.project.name}-${testInfo.retry}`,
  );

  await page.goto(`/#/datasets/${datasetId}/review`);
  await expect(page).toHaveURL(new RegExp(`#/datasets/${datasetId}/review$`));
  await expect(page.getByRole('heading', { name: 'Review photos', level: 1 })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`#/datasets/${datasetId}/review$`));
  await expect(page.getByRole('heading', { name: 'Review photos', level: 1 })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Dataset steps' })).toBeVisible();
  const desktopCurrent = page.getByRole('button', { name: /Review photos Current/ });
  if (await desktopCurrent.isVisible()) {
    await expect(desktopCurrent).toHaveAttribute('aria-current', 'step');
  } else {
    await expect(page.getByLabel(/Step \d+ of \d+/)).toHaveValue('review');
  }
  await expect(page.getByText('Import an existing dataset ZIP')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Export ZIP/ })).toHaveCount(0);
  expect(await accessibilityViolations(page)).toEqual([]);

  await page.getByRole('button', { name: /Continue/ }).click();
  await expect(page).toHaveURL(new RegExp(`#/datasets/${datasetId}/anchors$`));
  await expect(page.getByRole('heading', { name: 'Choose photos for generation', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Choose photos for generation', level: 1 })).toBeFocused();

  const stepPicker = page.getByLabel(/Step \d+ of \d+/);
  if (await stepPicker.isVisible()) {
    await stepPicker.selectOption('reference');
  } else {
    await page.getByRole('button', { name: /Set primary reference Optional/ }).click();
  }
  await expect(page.getByRole('heading', { name: 'Set primary reference', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Skip optional step' }).click();
  await expect(page).toHaveURL(new RegExp(`#/datasets/${datasetId}/generate$`));
  await expect(page.getByRole('heading', { name: 'Generate missing views', level: 1 })).toBeVisible();

  await page.goto(`/#/datasets/${datasetId}/not-a-step`);
  await expect(page.getByRole('heading', { name: 'Check photo variety', level: 1 })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`#/datasets/${datasetId}/coverage$`));

  const concept = await postJson(page, '/api/dataset/create', {
    name: `Concept flow ${testInfo.project.name}-${testInfo.retry}`,
    trigger_word: `z_concept_${testInfo.project.name}_${testInfo.retry}`,
    kind: 'concept',
    concept_desc: 'a recurring light trail',
  });
  expect(concept.status).toBe(200);
  await page.goto(`/#/datasets/${concept.body.id}/anchors`);
  await expect(page).toHaveURL(new RegExp(`#/datasets/${concept.body.id}/import$`));
  await expect(page.getByRole('heading', { name: 'Import photos', level: 1 })).toBeVisible();
  await expect(page.getByText('Step 1 of 9', { exact: true }).last()).toBeVisible();
  await expect(page.getByRole('button', { name: /Choose photos for generation/ })).toHaveCount(0);

  await page.goto('/#/datasets/2147483647/review');
  await expect(page).toHaveURL(/#\/datasets$/);
  await expect(page.getByRole('heading', { name: 'Datasets', level: 1 })).toBeVisible();
});

test('re-caption protects authored captions until the explicit override', async ({ page }, testInfo) => {
  const suffix = `${testInfo.project.name}-${testInfo.retry}`;
  await openDatasets(page);
  const { datasetId, imageIds } = await seedImportedDataset(
    page, `Recaption ${suffix}`, 2,
  );
  for (const [index, imageId] of imageIds.entries()) {
    const saved = await postJson(page, `/api/dataset/image/${imageId}/caption`, {
      caption: index ? 'machine fixture' : 'my carefully edited caption',
    });
    expect(saved.status).toBe(200);
  }

  let secondOrigin = 'joycaption';
  const captionBodies = [];
  await page.route(`**/api/dataset/${datasetId}/**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'POST' && pathname === `/api/dataset/${datasetId}/caption`) {
      captionBodies.push(request.postDataJSON());
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, captioned: secondOrigin === 'asserted' ? 2 : 1 }) });
      return;
    }
    if (request.method() === 'GET' && pathname === `/api/dataset/${datasetId}/images`) {
      const response = await route.fetch();
      const body = await response.json();
      body.images = body.images.map((image) => (
        image.id === imageIds[1] ? { ...image, caption_origin: secondOrigin } : image
      ));
      await route.fulfill({ response, json: body });
      return;
    }
    await route.continue();
  });

  await page.evaluate((id) => localStorage.setItem('datasetCurrentId', String(id)), datasetId);
  await page.goto('/#/datasets?section=captions');
  // Hash-only navigation keeps the already-mounted dataset hook alive; reload
  // once so it reads the seeded hand-off value exactly as a reopened tab does.
  await page.reload();
  const recaption = page.getByRole('button', { name: /Re-caption/ });
  const override = page.getByRole('checkbox', { name: /Also replace captions I wrote \(1\)/ });
  await expect(recaption).toBeEnabled();
  await expect(override).not.toBeChecked();

  await recaption.click();
  let dialog = page.getByRole('alertdialog', { name: 'Re-caption 1 kept images?' });
  await expect(dialog).toContainText('1 machine-written');
  await expect(dialog).toContainText('spare the 1 caption you wrote');
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect.poll(() => captionBodies.length).toBe(1);
  expect(captionBodies[0]).toEqual({ force: true, mode: 'prose' });
  await expect(override).not.toBeChecked();

  await override.check();
  await recaption.click();
  dialog = page.getByRole('alertdialog', { name: 'Replace 2 caption entries?' });
  await expect(dialog).toContainText('also replace the 1 caption you wrote');
  await dialog.getByRole('button', { name: 'Continue' }).click();
  const danger = page.getByRole('alertdialog', { name: 'Replace your captions too?' });
  await expect(danger).toContainText('cannot be undone as one batch');
  await danger.getByRole('button', { name: 'Replace my captions' }).click();
  await expect.poll(() => captionBodies.length).toBe(2);
  expect(captionBodies[1]).toEqual({
    force: true, mode: 'prose', include_asserted: true,
  });
  await expect(override).not.toBeChecked();

  secondOrigin = 'asserted';
  await page.reload();
  await expect(page.getByRole('checkbox', {
    name: /Also replace captions I wrote \(2\)/,
  })).not.toBeChecked();
  await expect(recaption).toBeDisabled();
  await expect(recaption).toHaveAttribute('title', /Every existing caption is yours/);
});

test('outdated analysis refreshes explicitly and preserves review evidence', async ({ page }, testInfo) => {
  const suffix = `${testInfo.project.name}-${testInfo.retry}`;
  await openDatasets(page);
  const { datasetId, imageIds } = await seedImportedDataset(page, `Analysis ${suffix}`);
  const coverage = await postJson(page, `/api/dataset/image/${imageIds[0]}/coverage`, {
    framing: 'face', angle: 'front', expression: 'neutral', lighting: 'studio',
    pose: 'headshot', background: 'plain', occlusion: 'none',
  });
  expect(coverage.status).toBe(200);

  let legacy = true;
  let analyzeCalls = 0;
  await page.route(`**/api/dataset/${datasetId}/**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'POST'
        && pathname === `/api/dataset/${datasetId}/corpus/analyze`) {
      analyzeCalls += 1;
      legacy = false;
      const response = await route.fetch();
      await route.fulfill({ response });
      return;
    }
    if (request.method() === 'GET' && pathname === `/api/dataset/${datasetId}/images`) {
      const response = await route.fetch();
      const body = await response.json();
      body.images = body.images.map((image) => ({
        ...image,
        analysis: {
          ...image.analysis,
          analysis_version: legacy ? 1 : 2,
          face: { quality: 'green', face_sharpness: 81 },
        },
      }));
      await route.fulfill({ response, json: body });
      return;
    }
    await route.continue();
  });

  await page.evaluate((id) => localStorage.setItem('datasetCurrentId', String(id)), datasetId);
  await page.goto(`/#/datasets/${datasetId}/coverage`);
  const refresh = page.getByRole('button', {
    name: '📐 Refresh local analysis (1 outdated)', exact: true,
  });
  await expect(refresh).toBeVisible();
  expect(analyzeCalls).toBe(0);
  await expect(page.getByText(/analysis outdated/)).toBeVisible();
  await expect(page.getByText(/face pixels green/)).toBeVisible();
  await expect(page.getByLabel('lighting')).toHaveValue('studio');
  await expect(refresh).toHaveAttribute('title', /bokeh-aware sharpness scoring/);

  await refresh.click();
  await expect.poll(() => analyzeCalls).toBe(1);
  await expect(page.getByRole('button', {
    name: '📐 Refresh local analysis', exact: true,
  })).toBeVisible();
  await expect(page.getByText(/analysis current/)).toBeVisible();
  await expect(page.getByText(/face pixels green/)).toBeVisible();
  await expect(page.getByLabel('lighting')).toHaveValue('studio');
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
    ['guide', 'Open the app'],
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

test('the rendered guide exposes all first-run pages in order', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/guide/getting-started');
  const guidePages = [
    ['getting-started', 'Open the app'],
    ['image-provider', 'Choose an image provider'],
    ['comfyui', 'Configure ComfyUI'],
    ['local-vision', 'Configure local vision'],
    ['quality-tools', 'Install quality tools'],
    ['training-tools', 'Configure training'],
    ['create-dataset', 'Create a dataset'],
    ['import-photos', 'Import photos'],
    ['review-corpus', 'Review photos'],
    ['choose-anchors', 'Choose photos for generation'],
    ['plan-coverage', 'Check photo variety'],
    ['primary-reference', 'Set a primary reference'],
    ['generate-gaps', 'Generate missing views'],
    ['curate-images', 'Curate images'],
    ['caption-images', 'Caption images'],
    ['score-images', 'Score face similarity'],
    ['export-dataset', 'Export dataset'],
    ['train-lora', 'Train a LoRA'],
    ['review-checkpoints', 'Review checkpoints'],
    ['test-studio', 'Test in Studio'],
    ['back-up', 'Back up dataset'],
  ];

  const pagePicker = page.getByLabel('Guide page');
  if (await pagePicker.isVisible()) {
    await pagePicker.selectOption('back-up');
    await expect(page.getByRole('heading', { name: 'Back up dataset', level: 1 })).toBeVisible();
    await pagePicker.selectOption('getting-started');
  }

  for (const [index, [id, title]] of guidePages.entries()) {
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();
    await expect(page.getByText(`${index + 1} of ${guidePages.length}`, { exact: true })).toBeVisible();
    if (await pagePicker.isVisible()) {
      await expect(pagePicker).toHaveValue(id);
    }
    if (index > 0) {
      await expect(page.getByRole('link', {
        name: `Previous ${guidePages[index - 1][1]}`,
      })).toBeVisible();
    }
    if (index < guidePages.length - 1) {
      await page.getByRole('link', { name: `Next ${guidePages[index + 1][1]}` }).click();
    }
  }
  await expect(page.getByRole('link', { name: /^Next / })).toHaveCount(0);

  await page.goto('/#/guide/dataset-guide');
  await expect(page.getByRole('heading', { name: 'Building a good dataset', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: /^Previous / })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Next Troubleshooting' })).toBeVisible();
});

test('activating the current guide heading link always restores focus and scroll', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/guide/getting-started');
  const onThisPage = page.getByRole('navigation', { name: 'On this page' });
  const doThisLink = onThisPage.getByRole('link', { name: 'Do this' });
  const doThisSection = page.locator('#do-this');

  await doThisLink.click();
  await expect(page).toHaveURL(/heading=do-this/);
  await expect(doThisSection).toBeFocused();
  await page.getByRole('heading', { name: 'Open the app', level: 1 }).focus();
  await page.evaluate(() => window.scrollTo(0, 0));
  await doThisLink.click();

  await expect(doThisSection).toBeFocused();
  await expect.poll(() => doThisSection.evaluate((section) => (
    section.getBoundingClientRect().top < window.innerHeight
  ))).toBe(true);
});
