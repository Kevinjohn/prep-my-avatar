import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(frontendDir, '..');
const outputDir = resolve(root, 'docs/screenshots/guide');
const port = '5076';
const baseURL = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, [resolve(root, 'scripts/e2e-server.mjs')], {
  cwd: root,
  env: { ...process.env, E2E_PORT: port },
  stdio: 'inherit',
});

const screenshots = [
  ['01_open_app', null, 'Welcome to Prep My Avatar'],
  ['02_choose_image_provider', /Image generation — API keys & provider/, 'Image generation'],
  ['03_configure_comfyui', /Local generation — ComfyUI/, 'ComfyUI — local generation & Test Studio'],
  ['04_configure_local_vision', /Local vision —/, 'Local vision — Ollama, LM Studio, or llama.cpp'],
  ['05_install_quality_tools', /Quality tools — ML extras/, 'Quality tools (ML extras)'],
  ['06_configure_training', /LoRA training — ai-toolkit/, 'LoRA training — ai-toolkit'],
];

const workflow = [
  ['09_review_corpus', 'review', 'Review corpus'],
  ['10_choose_anchors', 'anchors', 'Choose anchors'],
  ['11_review_coverage', 'coverage', 'Review coverage'],
  ['12_set_primary_reference', 'reference', 'Set primary reference'],
  ['13_generate_missing_views', 'generate', 'Generate missing views'],
  ['14_curate_images', 'curate', 'Curate images'],
  ['15_caption_images', 'captions', 'Caption images'],
  ['16_score_face_similarity', 'score', 'Score face similarity'],
  ['17_export_dataset', 'export', 'Export dataset'],
  ['18_train_lora', 'train', 'Train a LoRA'],
  ['19_review_checkpoints', 'checkpoints', 'Review checkpoints'],
  ['20_test_studio', 'studio', 'Test in Studio'],
  ['21_back_up_dataset', 'backup', 'Back up dataset'],
];

function stopServer() {
  if (!server.killed) server.kill('SIGTERM');
}

async function waitForServer() {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`Screenshot server exited with ${server.exitCode}`);
    try {
      const response = await fetch(`${baseURL}/api/health/ready`);
      if (response.ok) return;
    } catch {
      // The isolated backend is still starting.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error('Timed out waiting for the screenshot server');
}

async function capture(page, name) {
  await page.screenshot({
    path: resolve(outputDir, `${name}.jpg`),
    type: 'jpeg',
    quality: 88,
    animations: 'disabled',
  });
}

async function postJson(page, path, body) {
  return page.evaluate(async ({ requestPath, requestBody }) => {
    const token = document.cookie.match(/csrf_token=([^;]+)/)?.[1] || '';
    const response = await fetch(requestPath, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': decodeURIComponent(token),
      },
      body: JSON.stringify(requestBody),
    });
    return { status: response.status, body: await response.json() };
  }, { requestPath: path, requestBody: body });
}

async function closeNotifications(page) {
  const closeButtons = page.getByRole('button', { name: 'Close notification' });
  while (await closeButtons.count()) await closeButtons.first().click();
}

async function sanitizeCapture(page, name) {
  if (name !== '05_install_quality_tools') return;
  // The installer deliberately renders an absolute fallback command. Keep the
  // real screen state while preventing a maintainer's home path from becoming
  // part of public documentation.
  await page.locator('code').first().waitFor();
  await page.locator('code').evaluateAll((nodes) => {
    for (const node of nodes) node.textContent = 'python -m pip install …';
  });
}

async function finishImageReview(page, images) {
  for (const [index, image] of images.entries()) {
    const status = await postJson(page, `/api/dataset/image/${image.id}/status`, { status: 'keep' });
    if (status.status !== 200) throw new Error(`Could not keep image ${image.id}`);
    const caption = await postJson(page, `/api/dataset/image/${image.id}/caption`, {
      caption: [
        'portrait photo, neutral expression, soft indoor light',
        'close portrait, looking at camera, blurred background',
        'sharp head-and-shoulders photo, even daylight',
        'three-quarter portrait, plain background, natural light',
      ][index],
    });
    if (caption.status !== 200) throw new Error(`Could not caption image ${image.id}`);
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  await waitForServer();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));

  try {
    for (const [name, row, heading] of screenshots) {
      await page.goto(`${baseURL}/#/setup`);
      // Hash navigation keeps SetupPage mounted, including its current wizard
      // screen. Reload so every capture begins from the same welcome state.
      await page.reload();
      await page.getByRole('heading', { name: 'Welcome to Prep My Avatar', level: 1 }).waitFor();
      if (row) await page.getByRole('button', { name: row }).click();
      await page.getByRole('heading', { name: heading, level: 1 }).waitFor();
      await sanitizeCapture(page, name);
      await capture(page, name);
    }

    await page.goto(`${baseURL}/#/datasets`);
    await page.getByRole('heading', { name: 'Datasets', level: 1 }).waitFor();
    await capture(page, '07_create_dataset');
    await page.getByLabel('Character name').fill('Alex Demo');
    await page.getByLabel(/^Trigger word/).fill('zchar_alex');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.getByRole('heading', { name: 'Import photos', level: 1 }).waitFor();
    const datasetId = new URL(page.url()).hash.match(/datasets\/(\d+)/)?.[1];
    if (!datasetId) throw new Error(`Could not read dataset id from ${page.url()}`);
    await closeNotifications(page);
    await capture(page, '08_import_photos');

    const corpus = [
      'placeholder_blur_with_speck.jpg',
      'placeholder_bokeh_subject.jpg',
      'placeholder_sharp.jpg',
      'placeholder_uniform_blur.jpg',
    ].map((name) => resolve(root, 'tasks/reference-corpus', name));
    await page.locator('input[type="file"][accept="image/*"][multiple]').setInputFiles(corpus);
    await page.waitForFunction(async (id) => {
      const response = await fetch(`/api/dataset/${id}?include_images=1`);
      const dataset = await response.json();
      return dataset.images?.length === 4;
    }, datasetId, { timeout: 60_000 });
    await page.getByText(/GPU processing in progress/).waitFor({
      state: 'hidden', timeout: 60_000,
    });

    const payload = await page.evaluate(async (id) => (
      fetch(`/api/dataset/${id}?include_images=1`).then((response) => response.json())
    ), datasetId);

    for (const [name, slug, heading] of workflow) {
      await page.goto(`${baseURL}/#/datasets/${datasetId}/${slug}`);
      await page.getByRole('heading', { name: heading, level: 1 }).waitFor();
      if (slug === 'reference') {
        await page.locator('input[type="file"][accept="image/*"]:not([multiple])').first()
          .setInputFiles(resolve(root, 'tasks/reference-corpus/placeholder_sharp.jpg'));
        await page.getByAltText('ref').waitFor({ timeout: 60_000 });
      }
      await closeNotifications(page);
      await page.waitForTimeout(150);
      await capture(page, name);
      // Step 9 documents the undecided review state. Complete that review only
      // after its capture so subsequent pages show a realistic accepted set.
      if (slug === 'review') {
        await finishImageReview(page, payload.images);
        await page.reload();
        await page.getByText('accepted for training 4', { exact: true }).waitFor();
      }
    }
  } finally {
    await browser.close();
  }
}

try {
  await main();
} finally {
  stopServer();
}
