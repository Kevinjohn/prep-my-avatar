import { test, expect } from '@playwright/test';
import axe from 'axe-core';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

test('hosted export requires exact review, invalidates edits, and keeps errors visible', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  const dataset = await page.evaluate(async () => {
    const csrf = decodeURIComponent(document.cookie.match(/csrf_token=([^;]+)/)?.[1] || '');
    const response = await fetch('/api/dataset/create', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ name: 'Hosted synthetic fixture', trigger_word: 'demo_person' }) });
    return response.json();
  });
  const source = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
  const snapshot = { dataset_revision: 'demo-revision', subject: { name: 'Demo person', trigger_word: 'demo_person' }, recipes: [{ id: 'fal-krea-reviewed', version: 1, name: 'Reviewed hosted Krea', crop_rule: 'square', input_requirements: { minimum_training_images: 1 }, defaults: { resolution: 1024, steps: 1000, learning_rate: 0.0005, auto_captioning: 'Off', debug_dataset: false }, parameters: {} }], images: [{ id: 9, eligible: true, width: 800, height: 1200, caption: 'demo_person standing', source_preview_url: source, original_lineage: 'demo-source', status: 'keep' }] };
  let previews = 0;
  let rejectPreview = false;
  await page.route(`**/api/dataset/${dataset.id}/hosted-export**`, async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: snapshot });
    if (route.request().url().endsWith('/preview')) {
      previews += 1;
      if (rejectPreview) return route.fulfill({ status: 400, json: { error: 'Crop is outside the source image.' } });
      const request = route.request().postDataJSON();
      return route.fulfill({ json: { image_data_url: source, image_sha256: `image-${previews}`, caption_sha256: `caption-${previews}`, pair_sha256: `pair-${previews}`, caption: request.caption_override ?? 'demo_person standing', crop: [0, 1 / 6, 1, 5 / 6], warnings: ['Square crop may remove face or body content.'] } });
    }
    return route.fulfill({ status: 409, json: { error: 'Dataset changed. Reload and review again.' } });
  });
  await page.goto(`/#/datasets/${dataset.id}/export`);
  await page.getByRole('button', { name: 'Prepare hosted export' }).click();
  await page.getByLabel('Hosted subject name').fill('Synthetic subject');
  await page.getByLabel('Rights basis').selectOption('owned');
  await page.getByLabel('Publication scope').fill('Private preparation');
  await page.getByLabel('I have consent').check();
  await page.getByLabel('Photo 9 training').check();
  const download = page.getByRole('button', { name: 'Download reviewed hosted package' });
  await expect(download).toBeDisabled();
  await page.getByRole('button', { name: 'Preview training photo 9' }).click();
  await page.getByLabel('Approve exact training image and caption for photo 9').check();
  await expect(download).toBeEnabled();
  await page.getByLabel('Training caption override for photo 9').fill('demo_person portrait');
  await expect(download).toBeDisabled();
  await page.getByRole('button', { name: 'Preview training photo 9' }).click();
  await page.getByLabel('Approve exact training image and caption for photo 9').check();
  await download.click();
  await expect(page.getByRole('alert')).toContainText('Dataset changed');
  rejectPreview = true;
  await page.getByLabel('Training caption override for photo 9').fill('new target caption');
  await page.getByRole('button', { name: 'Preview training photo 9' }).click();
  await expect(page.getByRole('alert')).toContainText('Crop is outside');
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })).violations);
  expect(violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});


test('real offline package contains reviewed training pairs and separate reference/evaluation assets', async ({ page }, testInfo) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  const fixture = await page.evaluate(async (suffix) => {
    const post = async (url, body) => {
      const csrf = decodeURIComponent(document.cookie.match(/csrf_token=([^;]+)/)?.[1] || '');
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    };
    const dataset = await post('/api/dataset/create', { name: `Hosted raster fixture ${suffix}`, trigger_word: 'demo_person' });
    for (let index = 0; index < 3; index += 1) {
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 960;
      const context = canvas.getContext('2d');
      context.fillStyle = ['#da6734', '#297daf', '#779331'][index]; context.fillRect(0, 0, 640, 960);
      context.fillStyle = '#f2e2b0'; context.fillRect(50 + index * 60, 90 + index * 80, 170, 340);
      context.fillStyle = '#163045'; context.beginPath(); context.arc(430 - index * 45, 700 - index * 130, 90 + index * 20, 0, Math.PI * 2); context.fill();
      const blob = await new Promise((done) => canvas.toBlob(done, 'image/png'));
      const data = new FormData(); data.append('files', blob, `synthetic_${index}.png`); data.append('crop', '0');
      data.append('csrf_token', decodeURIComponent(document.cookie.match(/csrf_token=([^;]+)/)?.[1] || ''));
      const imported = await fetch(`/api/dataset/${dataset.id}/import`, { method: 'POST', body: data });
      if (!imported.ok) throw new Error(await imported.text());
    }
    const payload = await (await fetch(`/api/dataset/${dataset.id}?include_images=1`)).json();
    for (const image of payload.images) {
      await post(`/api/dataset/image/${image.id}/status`, { status: 'keep' });
      await post(`/api/dataset/image/${image.id}/caption`, { caption: `synthetic geometry ${image.id}` });
    }
    return { id: dataset.id, images: payload.images.map((image) => image.id) };
  }, `${testInfo.project.name}-${testInfo.retry}`);
  const [training, reference, evaluation] = fixture.images;
  await page.goto(`/#/datasets/${fixture.id}/export`);
  await page.getByRole('button', { name: 'Prepare hosted export' }).click();
  await page.getByLabel('Rights basis').selectOption('owned');
  await page.getByLabel('Publication scope').fill('Private synthetic regression fixture');
  await page.getByLabel('I have consent').check();
  await page.getByLabel(`Photo ${training} training`, { exact: true }).check();
  await page.getByLabel(`Photo ${reference} reference`, { exact: true }).check();
  await page.getByLabel(`Photo ${evaluation} evaluation`, { exact: true }).check();
  await page.getByLabel(`Reference purpose for photo ${reference}`).fill('Identity view');
  const downloadButton = page.getByRole('button', { name: 'Download reviewed hosted package' });
  const previewAndApprove = async (imageId, role) => {
    await page.getByRole('button', { name: `Preview ${role} photo ${imageId}`, exact: true }).click();
    const approval = page.getByLabel(`Approve exact ${role} image and caption for photo ${imageId}`);
    await expect(approval).toBeVisible(); await approval.check();
  };
  await previewAndApprove(training, 'training');
  await page.getByLabel(`Training crop top for photo ${training}`).fill('0');
  await expect(page.getByLabel(`Approve exact training image and caption for photo ${training}`)).toHaveCount(0);
  await expect(downloadButton).toBeDisabled();
  await page.getByLabel(`Training caption override for photo ${training}`).fill('reviewed square geometry');
  await previewAndApprove(training, 'training');
  await previewAndApprove(reference, 'reference');
  await previewAndApprove(evaluation, 'evaluation');
  await expect(downloadButton).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath('hosted_export_review.png'), fullPage: true });
  const downloadable = page.waitForEvent('download'); await downloadButton.click();
  const downloaded = await downloadable;
  const packagePath = testInfo.outputPath('reviewed_hosted_package.zip'); await downloaded.saveAs(packagePath);
  const localPython = resolve(process.cwd(), '../.venv/bin/python');
  const result = JSON.parse(execFileSync(existsSync(localPython) ? localPython : 'python3', ['-c', `
import sys, json, zipfile, hashlib, io
from PIL import Image
with zipfile.ZipFile(sys.argv[1]) as outer:
    manifest_path = next(name for name in outer.namelist() if name.endswith('/manifest.json'))
    prefix = manifest_path[:-len('manifest.json')]
    manifest = json.loads(outer.read(manifest_path))
    for name, digest in manifest['files'].items():
        assert hashlib.sha256(outer.read(prefix + name)).hexdigest() == digest, name
    archive_name = manifest['recipe']['definition']['archive_name']
    with zipfile.ZipFile(io.BytesIO(outer.read(prefix + archive_name))) as training:
        assert all('/' not in name for name in training.namelist())
        sizes = {}
        for entry in manifest['entries']:
            archive = training if entry['role'] == 'training' else outer
            path_prefix = '' if entry['role'] == 'training' else prefix
            image = archive.read(path_prefix + entry['image_path'])
            caption = archive.read(path_prefix + entry['caption_path'])
            assert hashlib.sha256(image).hexdigest() == entry['image_sha256'] == entry['approved_image_sha256']
            assert hashlib.sha256(caption).hexdigest() == entry['caption_sha256'] == entry['approved_caption_sha256']
            assert caption.decode('utf-8') == entry['caption']
            assert entry['approved_pair_sha256']
            sizes[entry['role']] = Image.open(io.BytesIO(image)).size
        print(json.dumps({'roles': sorted(entry['role'] for entry in manifest['entries']), 'sizes': sizes, 'training_caption': next(entry['caption'] for entry in manifest['entries'] if entry['role'] == 'training'), 'reference_purpose': next(entry['reference_role'] for entry in manifest['entries'] if entry['role'] == 'reference')}))
`, packagePath], { encoding: 'utf8' }));
  expect(result.roles).toEqual(['evaluation', 'reference', 'training']);
  expect(result.sizes.training).toEqual([1024, 1024]);
  expect(result.sizes.reference).toEqual([640, 960]);
  expect(result.sizes.evaluation).toEqual([640, 960]);
  expect(result.training_caption).toBe('demo_person, reviewed square geometry');
  expect(result.reference_purpose).toBe('Identity view');
  const masters = await page.evaluate(async (id) => (await (await fetch(`/api/dataset/${id}?include_images=1`)).json()).images, fixture.id);
  expect(masters.find((image) => image.id === training).caption).toBe(`synthetic geometry ${training}`);
});


test('stale preview completion cannot change reopened loading state and second recipe drives controls', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('lds_setup_redirected', '1'));
  await page.goto('/#/datasets');
  const dataset = await page.evaluate(async () => {
    const csrf = decodeURIComponent(document.cookie.match(/csrf_token=([^;]+)/)?.[1] || '');
    return (await fetch('/api/dataset/create', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ name: 'Lifecycle synthetic fixture', trigger_word: 'demo_lifecycle' }) })).json();
  });
  const snapshot = { dataset_revision: 1, subject: { name: 'Synthetic subject', trigger_word: 'demo_lifecycle' }, recipes: [
    { id: 'square-demo', version: 1, name: 'Square fixture', crop_rule: 'square', input_requirements: { minimum_training_images: 1 }, parameters: { resolution: { type: 'integer', enum: [640] } }, defaults: { resolution: 640 } },
    { id: 'preserve-demo', version: 2, name: 'Preserve fixture', crop_rule: 'preserve', input_requirements: { minimum_training_images: 2 }, count_guidance: { training: 10 }, parameters: { passes: { type: 'integer', minimum: 2, maximum: 8 }, quality_mode: { type: 'string', enum: ['Standard', 'Fine'] } }, defaults: { passes: 5, quality_mode: 'Fine' } },
  ], images: [{ id: 7, width: 640, height: 960, eligible: true, caption: 'master caption', original_lineage: 7 }] };
  let loads = 0;
  let releasePreview;
  let releaseReload;
  let capturedPreview;
  await page.route(`**/api/dataset/${dataset.id}/hosted-export**`, async (route) => {
    if (route.request().method() === 'GET') {
      loads += 1;
      if (loads === 1) return route.fulfill({ json: snapshot });
      return new Promise((done) => { releaseReload = async () => { await route.fulfill({ json: snapshot }); done(); }; });
    }
    if (loads === 1) return new Promise((done) => { releasePreview = async () => { await route.fulfill({ status: 400, json: { error: 'Old preview failure' } }); done(); }; });
    capturedPreview = route.request().postDataJSON();
    return route.fulfill({ json: { image_data_url: '', caption: 'demo_lifecycle', image_sha256: 'i', caption_sha256: 'c', pair_sha256: 'p', warnings: [] } });
  });
  await page.goto(`/#/datasets/${dataset.id}/export`);
  await page.getByRole('button', { name: 'Prepare hosted export' }).click();
  await page.getByLabel('Photo 7 training', { exact: true }).check();
  await page.getByRole('button', { name: 'Preview training photo 7' }).click();
  await expect.poll(() => Boolean(releasePreview)).toBe(true);
  await page.getByRole('button', { name: 'Close hosted draft' }).click();
  await page.getByRole('button', { name: 'Prepare hosted export' }).click();
  await expect.poll(() => Boolean(releaseReload)).toBe(true);
  const oldCompletion = page.waitForResponse((response) => response.url().endsWith('/hosted-export/preview'));
  await releasePreview(); await oldCompletion;
  await expect(page.getByRole('status').filter({ hasText: 'Loading' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await releaseReload();
  await page.getByLabel('Hosted recipe').selectOption('preserve-demo:2');
  await expect(page.getByLabel('passes')).toHaveValue('5');
  await expect(page.getByLabel('passes')).toHaveAttribute('min', '2');
  await expect(page.getByLabel('passes')).toHaveAttribute('max', '8');
  await expect(page.getByLabel('quality mode')).toHaveValue('Fine');
  await expect(page.getByText('Planning guidance: 10 training photos.', { exact: false })).toBeVisible();
  await expect(page.getByText('Choose at least 2 training photo(s).')).toBeVisible();
  await expect(page.getByLabel('Training crop top for photo 7')).toHaveCount(0);
  await page.getByLabel('Training caption override for photo 7').fill('temporary');
  await page.getByLabel('Training caption override for photo 7').fill('');
  await page.getByRole('button', { name: 'Preview training photo 7' }).click();
  await expect.poll(() => capturedPreview?.caption_override).toBe('');
  expect(capturedPreview.crop).toBeNull();
  await page.getByRole('button', { name: 'Use master caption for training photo 7' }).click();
  await page.getByRole('button', { name: 'Preview training photo 7' }).click();
  await expect.poll(() => capturedPreview?.caption_override).toBeNull();
});
