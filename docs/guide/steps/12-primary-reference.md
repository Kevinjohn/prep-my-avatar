# Step 12: Set a primary reference

The primary reference is used by local FLUX.2 Klein and by optional face-similarity scoring. Remote API engines can use the reviewed anchor set instead.

This is a Character-only step. Concept and Style datasets do not show a primary-reference control; if you chose either kind, skip this page.

## Before you begin

Skip this page only if you will use neither local Klein nor face-similarity scoring. Otherwise, choose a sharp, accepted image with an unobstructed face and a neutral enough angle to identify the person reliably.

## Do this

1. Open **Set primary reference** in the dataset step navigator. Its URL ends in `/reference` and it is labelled **Optional**.
2. Select or drop the best reference photo.
3. Open the crop control and keep the face clear without cutting off important features.
4. Add up to three extra references only when another angle adds useful identity evidence.
5. Remove any weak or incorrect extra reference.
6. Confirm the preview shows the intended person and no unrelated face dominates the frame.
7. Select **Continue**, or select **Skip optional step** if neither local Klein nor face scoring needs a reference.

The reference is not automatically your entire training set. It is an identity input for local Klein and face scoring; accepted images still determine what is available for training.

## You are finished when

For Character, the preview shows the intended image and the navigator marks **Set primary reference — Complete**, or you deliberately used **Skip optional step**. Concept and Style navigators omit this page.
