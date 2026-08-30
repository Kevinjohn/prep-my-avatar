# Step 15: Caption the kept images

A caption tells the training model what is visible in each image. The thing you are teaching must be left out: Character captions omit identity traits, Concept captions omit the concept, and Style captions describe content rather than the visual style.

## Before you begin

Keep and reject images before captioning. Automatic captioning needs a ready local-vision backend. Without one, you can type captions manually on each kept image.

## Do this

1. Open **Captions** in the dataset sidebar.
2. Confirm the caption style. Use prose for the prose-based model families; use booru tags for an SDXL booru workflow.
3. Select **Caption the kept ones** and wait for the count to finish.
4. Read every caption. Correct factual mistakes and remove descriptions of the training target.
5. Open the identity- or concept-leak badge and fix every highlighted caption.
6. Use **Caption tools** for a repeated find-and-replace across the set.
7. If another trainer needs sidecar files, use **Write .txt files** after the captions are final.

## You are finished when

The kept count and captioned count match, every caption is accurate, and the leak check reports no unresolved target descriptions. The Progress item **Caption** is checked.
