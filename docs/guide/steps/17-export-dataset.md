# Step 17: Export dataset

Export creates a standard training package from the images currently marked **kept**. It does not include rejected or undecided images.

## Before you begin

Finish curation and captions first. An export can be useful even if you never train inside Prep My Avatar.

## Do this

1. Open **Export dataset** in the dataset step navigator. Its URL ends in `/export`.
2. Check the kept count beside **Export ZIP**.
3. Select **Export ZIP**.
4. Choose a destination folder if your browser asks.
5. Wait for the download to finish, then open the ZIP to verify it contains image files and matching `.txt` caption files.
6. Keep `_prep_my_avatar_manifest.json`. Training tools can ignore it, but it records the source mix, coverage, and provenance.
7. Select **Continue to Train a LoRA**.

An export ZIP is a training package, not a complete backup of the project. The final guide step explains the separate **Backup** action.

## Reviewed hosted person pack

For a character dataset, choose **Prepare hosted export** in the same export step.
This works without a local trainer, service credentials or network access.

1. Confirm the subject, trigger, source rights, consent and intended publication scope.
2. Select training, reference and evaluation roles. Reference photos can also be training inputs; evaluation families and burst groups must remain separate. Give references a purpose and order.
3. Preview each selected role. For training, adjust the square crop and check that important face/body content remains. Wider references and evaluation photos retain their own framing.
4. Review the final caption beside the exact derivative. Approve each pair. Changing its crop, caption or relevant settings requires another preview and approval; master captions and originals are preserved.
5. Download the reviewed hosted package. Retain the complete private revision with `manifest.json`, `recipe.json`, `references/` and `evaluation/`. Only `krea_training.zip` is the trainer upload archive.

A draft is saved in this browser, but approvals must be repeated when reopening it.
Export makes no provider request and grants no upload or spending permission. See
the [manual pilot kit](https://github.com/Kevinjohn/prep-my-avatar/blob/69d099ee040ba54a386f5ac89ef83b960d177701/docs/hosted-pilots/README.md) for the reference baseline,
private records and silent-video review steps. Ordinary **Export ZIP** and
**Backup** remain separate actions.

## You are finished when

A ZIP file exists in your chosen download folder and its image/text pairs match the kept set. If export is your goal, skip the optional training, checkpoint-review, and Studio work in Steps 18–20, then continue to Step 21 to back up the dataset.
