# Step 16: Score face similarity

Face scoring is an optional review aid for Character datasets. It compares each kept face with the reference and shows which images deserve closer inspection. A score is not permission to keep or delete an image automatically.

## Before you begin

This page applies only when **Face-similarity scoring** was installed during Setup and a suitable reference photo is set. Skip it for Concept or Style datasets.

## Do this

1. Open **Curation**.
2. Select **Analyze faces**.
3. Wait for every kept image to receive a result. ComfyUI may pause while this local analysis uses the GPU or CPU.
4. Review low or orange results at full size. Check whether the face is actually wrong, obscured, too small, or simply seen from a difficult angle.
5. Reject an off-identity image manually. Keep a useful image when your own inspection shows the score is misleading.
6. Review sharpness and exposure warnings separately; identity and technical quality are different questions.

## You are finished when

Every kept Character image you intended to score has a result and every suspicious result has been reviewed. The optional Progress item **Score** is checked.
