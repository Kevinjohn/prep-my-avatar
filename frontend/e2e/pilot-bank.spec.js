import { test, expect } from "@playwright/test";
import axe from "axe-core";

async function createDataset(page, name) {
  await page.addInitScript(() =>
    sessionStorage.setItem("lds_setup_redirected", "1"),
  );
  await page.goto("/#/datasets");
  return page.evaluate(async (name) => {
    const csrf = decodeURIComponent(
      document.cookie.match(/csrf_token=([^;]+)/)?.[1] || "",
    );
    return (
      await fetch("/api/dataset/create", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ name, trigger_word: "demo_bank" }),
      })
    ).json();
  }, name);
}

test("real offline bank retains imported still review, first frame and downloadable evidence", async ({
  page,
}, testInfo) => {
  const dataset = await createDataset(page, "Private bank synthetic fixture");
  const [imageId, evaluationId] = await page.evaluate(async (id) => {
    const csrf = () =>
      decodeURIComponent(
        document.cookie.match(/csrf_token=([^;]+)/)?.[1] || "",
      );
    for (let i = 0; i < 2; i += 1) {
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = 960;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = ["#297daf", "#af7329"][i];
      ctx.fillRect(0, 0, 640, 960);
      ctx.fillStyle = "#f2e2b0";
      ctx.fillRect(100 + i * 100, 100, 200, 500);
      const blob = await new Promise((done) =>
        canvas.toBlob(done, "image/png"),
      );
      const data = new FormData();
      data.append("files", blob, `synthetic_${i}.png`);
      data.append("crop", "0");
      data.append("csrf_token", csrf());
      const response = await fetch(`/api/dataset/${id}/import`, {
        method: "POST",
        body: data,
      });
      if (!response.ok) throw new Error(await response.text());
    }
    const corpus = await (
      await fetch(`/api/dataset/${id}?include_images=1`)
    ).json();
    for (const image of corpus.images)
      await fetch(`/api/dataset/image/${image.id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ status: "keep" }),
      });
    return corpus.images.map((image) => image.id);
  }, dataset.id);
  await page.goto(`/#/datasets/${dataset.id}/export`);
  await page.getByRole("button", { name: "Prepare hosted export" }).click();
  await page.getByLabel("Hosted recipe").selectOption("reviewed-reference:1");
  await page.getByLabel("Rights basis").selectOption("owned");
  await page.getByLabel("Publication scope").fill("Private synthetic fixture");
  await page.getByLabel("I have consent").check();
  await page.getByLabel(`Photo ${imageId} reference`, { exact: true }).check();
  await page
    .getByLabel(`Reference purpose for photo ${imageId}`)
    .fill("Identity view");
  await page
    .getByRole("button", { name: `Preview reference photo ${imageId}` })
    .click();
  await page
    .getByLabel(
      `Approve exact reference image and caption for photo ${imageId}`,
    )
    .check();
  await page
    .getByLabel(`Photo ${evaluationId} evaluation`, { exact: true })
    .check();
  await page
    .getByRole("button", { name: `Preview evaluation photo ${evaluationId}` })
    .click();
  await page
    .getByLabel(
      `Approve exact evaluation image and caption for photo ${evaluationId}`,
    )
    .check();
  const exportDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download reviewed hosted package" })
    .click();
  await exportDownload;
  await page.getByRole("button", { name: "Close hosted draft" }).click();
  await page.getByRole("button", { name: "Open private asset bank" }).click();
  await page.getByLabel("Candidate recipe").selectOption("manual-still");
  await page.getByLabel("Prompt / scene notes").fill("Synthetic still fixture");
  await page
    .getByRole("button", { name: "Record attempt", exact: true })
    .click();
  await expect(page.getByLabel("Prompt / scene notes")).toHaveValue("");
  const attempt = page
    .getByRole("article")
    .filter({
      has: page.getByText("Import returned local file", { exact: true }),
    })
    .first();
  const evaluationRequest = page.waitForResponse(
    (response) =>
      response.url().includes(`/pilot-bank/exports/`) &&
      response.url().includes("manifest_sha256="),
  );
  await attempt.getByText("Compare held-out photos", { exact: true }).click();
  const heldOut = attempt.getByRole("img", {
    name: `Held-out evaluation photo ${evaluationId}`,
    exact: true,
  });
  await expect(heldOut).toBeVisible();
  expect((await evaluationRequest).ok()).toBe(true);
  await expect(heldOut).toHaveJSProperty("naturalWidth", 640);
  await expect(
    attempt.getByText("Review only; never sent as generation inputs.", {
      exact: false,
    }),
  ).toBeVisible();
  await attempt
    .getByText("Import returned local file", { exact: true })
    .click();
  const outputPng = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 480;
    const context = canvas.getContext("2d");
    context.fillStyle = "#779331";
    context.fillRect(0, 0, 320, 480);
    context.fillStyle = "#f2e2b0";
    context.fillRect(80, 80, 120, 280);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  await attempt.getByLabel("Returned file").setInputFiles({
    name: "synthetic_output.png",
    mimeType: "image/png",
    buffer: Buffer.from(outputPng, "base64"),
  });
  await attempt
    .getByRole("button", { name: "Import file into private bank" })
    .click();
  await expect(
    page.getByRole("img", { name: "Imported manual attempt output" }),
  ).toBeVisible();
  await expect(
    attempt.getByRole("button", { name: "Import file into private bank" }),
  ).toBeDisabled();
  await page.getByText("Review output", { exact: true }).click();
  await page.getByLabel("Accept this output").check();
  await page.getByLabel("Subject recognises likeness").check();
  await page
    .getByLabel("Acceptance / rejection reason")
    .fill("Synthetic review fixture, not hosted evidence");
  await page.getByLabel("Correction time (minutes)").fill("3");
  await page.getByRole("button", { name: "Save output review" }).click();
  await page.getByLabel("Candidate recipe").selectOption("manual-video");
  const frameSelect = page.getByLabel("Accepted first-frame still");
  await expect(frameSelect.locator("option")).toHaveCount(2);
  const fileId = await frameSelect
    .locator("option")
    .last()
    .getAttribute("value");
  await frameSelect.selectOption(fileId);
  await page
    .getByRole("button", { name: "Record attempt", exact: true })
    .click();
  await page.getByRole("button", { name: "Reload private bank" }).click();
  await expect(
    page.getByText("video · not_started", { exact: false }),
  ).toBeVisible();
  await page.getByText("Review output", { exact: true }).click();
  await expect(page.getByLabel("Acceptance / rejection reason")).toHaveValue(
    "Synthetic review fixture, not hosted evidence",
  );
  const assetAttempt = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: /^still ·/ }) });
  if (!(await assetAttempt.getByLabel("Returned file").isVisible()))
    await assetAttempt
      .getByText("Import returned local file", { exact: true })
      .click();
  await assetAttempt
    .getByRole("combobox", { name: "File kind", exact: true })
    .selectOption("weights");
  await assetAttempt.getByLabel("Returned file").setInputFiles({
    name: "synthetic_weights.safetensors",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("opaque synthetic fixture; not real model weights"),
  });
  await assetAttempt
    .getByRole("button", { name: "Import file into private bank" })
    .click();
  const assetOutput = assetAttempt
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: /^weights ·/ }) });
  await assetOutput
    .getByText("Update asset compatibility and evidence", { exact: true })
    .click();
  await assetOutput
    .getByLabel("Saved asset compatibility")
    .selectOption("declared");
  await assetOutput
    .getByText("Advanced saved asset evidence", { exact: true })
    .click();
  await assetOutput
    .getByLabel("Saved asset rights JSON")
    .fill('{"notes":"private synthetic fixture"}');
  const metadataResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/metadata") &&
      response.request().method() === "PATCH",
  );
  await assetOutput
    .getByRole("button", { name: "Save asset evidence" })
    .click();
  const updatedResponse = await metadataResponse;
  expect(updatedResponse.ok()).toBe(true);
  const updatedBank = await updatedResponse.json();
  const updatedAsset = updatedBank.attempts
    .flatMap((a) => a.outputs)
    .find((f) => f.kind === "weights");
  expect(updatedAsset.compatibility.status).toBe("declared");
  expect(updatedAsset.rights.notes).toBe("private synthetic fixture");
  expect(
    updatedBank.attempts
      .flatMap((a) => a.outputs)
      .filter((f) => f.kind === "weights"),
  ).toHaveLength(1);
  await expect(
    assetOutput.getByRole("button", { name: "Save asset evidence" }),
  ).toBeEnabled();
  await page.screenshot({
    path: testInfo.outputPath("private_asset_bank_review.png"),
    fullPage: true,
  });
  const downloaded = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download private asset bank" })
    .click();
  const zip = await downloaded;
  await zip.saveAs(testInfo.outputPath("private_person_asset_bank.zip"));
  expect(zip.suggestedFilename()).toContain(".zip");
  const snapshot = await page.evaluate(
    async (id) => await (await fetch(`/api/dataset/${id}/pilot-bank`)).json(),
    dataset.id,
  );
  expect(snapshot.attempts).toHaveLength(2);
  const still = snapshot.attempts.find((a) => a.process === "still");
  expect(still.outputs[0].review.accepted).toBe(true);
  expect(
    snapshot.attempts.find((a) => a.process === "video").first_frame.sha256,
  ).toBe(still.outputs[0].sha256);
});

test("stale close completion is ignored and version conflict requires explicit reload", async ({
  page,
}) => {
  const dataset = await createDataset(page, "Private bank lifecycle fixture");
  const snapshot = {
    schema_version: 1,
    version: 1,
    tools: {},
    exports: [
      {
        revision: "r1",
        manifest_sha256: "hash",
        entries: [
          {
            role: "reference",
            image_path: "refs/photo.png",
            image_sha256: "hash",
            reference_role: "Identity",
          },
        ],
      },
    ],
    attempts: [],
    recipes: [
      {
        id: "manual-still",
        version: 1,
        label: "Manual fixture",
        process: "still",
        provider: "manual",
        endpoint: "manual",
        model_id: "manual",
        base_family: "manual",
        parameters: {},
      },
    ],
  };
  let releaseOld;
  let loads = 0;
  let mutations = 0;
  await page.route(
    `**/api/dataset/${dataset.id}/pilot-bank**`,
    async (route) => {
      if (route.request().method() === "GET") {
        loads += 1;
        if (loads === 1)
          return new Promise((done) => {
            releaseOld = async () => {
              await route.fulfill({
                status: 500,
                json: { error: "Old bank failure" },
              });
              done();
            };
          });
        return route.fulfill({ json: snapshot });
      }
      mutations += 1;
      return route.fulfill({
        status: 409,
        json: { error: "Bank version changed" },
      });
    },
  );
  await page.goto(`/#/datasets/${dataset.id}/export`);
  await page.getByRole("button", { name: "Open private asset bank" }).click();
  await expect.poll(() => Boolean(releaseOld)).toBe(true);
  await page.getByRole("button", { name: "Close private asset bank" }).click();
  await page.getByRole("button", { name: "Open private asset bank" }).click();
  await expect(page.getByLabel("Provider", { exact: true })).toHaveValue(
    "manual",
  );
  await releaseOld();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page
    .getByLabel("Prompt / scene notes")
    .fill("Keep unsaved scene notes");
  await page
    .getByRole("button", { name: "Record attempt", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "will not be resubmitted",
  );
  await expect(
    page.getByRole("button", { name: "Record attempt", exact: true }),
  ).toBeDisabled();
  expect(mutations).toBe(1);
  await page.getByRole("button", { name: "Reload private bank" }).click();
  await expect(
    page.getByRole("button", { name: "Record attempt", exact: true }),
  ).toBeEnabled();
  await expect(page.getByLabel("Prompt / scene notes")).toHaveValue(
    "Keep unsaved scene notes",
  );
  await page.getByRole("button", { name: "Close private asset bank" }).click();
  await page.getByRole("button", { name: "Open private asset bank" }).click();
  await expect(page.getByLabel("Prompt / scene notes")).toHaveValue(
    "Keep unsaved scene notes",
  );
  await expect(
    page.getByRole("checkbox", { name: "Identity · refs/photo.png" }),
  ).toBeChecked();
  await page.addScriptTag({ content: axe.source });
  expect(
    await page.evaluate(
      async () =>
        (
          await window.axe.run(document, {
            runOnly: {
              type: "tag",
              values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
            },
          })
        ).violations,
    ),
  ).toEqual([]);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});
