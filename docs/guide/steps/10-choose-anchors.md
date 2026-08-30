# Step 10: Choose identity anchors

Anchors are the small set of reviewed photos that a remote image provider may receive with a generation request. They help generated candidates keep the correct identity.

This is a Character-only step. Concept and Style datasets do not show anchor controls; if you chose either kind, skip this page.

## Before you begin

Use only accepted, identity-accurate Character photos. An anchor should have a clear face, useful detail, and a viewpoint that adds something different from the other anchors.

## Do this

1. In **Corpus Workbench**, filter to accepted images if necessary.
2. Leave strong ordinary candidates on **Automatic** so the app can choose a bounded set for each request.
3. Select **📌 Pin** for a small number of identity-critical photos that must always be considered.
4. Select **⊘ Exclude** for any photo that must never be sent to a remote provider. Excluding it from API use does not remove it from local training.
5. Avoid pinning several near-identical photos; varied angles provide better evidence.
6. Check the **anchors/request** and **pinned** counts in the workbench summary.

If you use only local tools or never generate images, you may leave every accepted image on Automatic.

## You are finished when

For Character, Progress shows a selected total or you have deliberately kept the automatic selection, and no private photo is eligible for API use. For Concept or Style, the step is finished because the controls do not apply.
