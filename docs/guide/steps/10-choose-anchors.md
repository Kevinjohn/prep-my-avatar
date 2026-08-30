# Step 10: Choose anchors

Anchors are the small set of reviewed photos that a remote image provider may receive with a generation request. They help generated candidates keep the correct identity.

This is a Character-only step. Concept and Style datasets do not show anchor controls; if you chose either kind, skip this page.

## Before you begin

Use only accepted, identity-accurate Character photos. An anchor should have a clear face, useful detail, and a viewpoint that adds something different from the other anchors.

## Do this

1. Open **Choose anchors** in the dataset step navigator. Its URL ends in `/anchors`.
2. Filter to accepted images if necessary.
3. Leave strong ordinary candidates on **Automatic** so the app can choose a bounded set for each request.
4. Select **📌 Pin** for a small number of identity-critical photos that must always be considered.
5. Select **⊘ Exclude** for any photo that must never be sent to a remote provider. Excluding it from API use does not remove it from local training.
6. Avoid pinning several near-identical photos; varied angles provide better evidence.
7. Check the **anchors/request** and **pinned** counts, then select **Continue to Review coverage**.

If you use only local tools or never generate images, you may leave every accepted image on Automatic.

## You are finished when

For Character, the summary shows the expected automatic or pinned selection, every photo you do not consent to send is **Excluded**, and the step navigator marks **Choose anchors — Complete**. Concept and Style navigators omit this page.
