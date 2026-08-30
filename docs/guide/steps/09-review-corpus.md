# Step 9: Review the imported corpus

Review decides which imported images are allowed into the training set and records what each image contributes. Imported images begin as **Needs decision** and do not train until you accept them.

## Before you begin

Stay in **Add images** and find **Corpus Workbench**. If local vision is ready, it can propose classifications. Without local vision, use the manual controls.

## Do this

1. Select **Refresh local analysis**. This checks basic image quality and duplicates.
2. For a Character dataset, select **Map visual coverage** when local vision is available, or open each image's manual editor. Concept and Style datasets do not show Character visual-coverage controls; review their technical analysis and training admission instead.
3. For a Character dataset, record framing, angle, expression, lighting, pose, background, and occlusion where the app asks for them.
4. Inspect warnings instead of accepting them blindly. A warning is evidence to review, not an automatic rejection.
5. Select **✓ Accept** for usable images and **✕ Reject** for images that should not train.
6. Use **Accept clean** only after checking the set it will affect.
7. Record source rights and consent when the workbench requests them.

Reject blurred, unusable, or incorrect-subject images. Keep useful variety even when a photo is not aesthetically perfect.

## You are finished when

For Character, the **needs decision** and **needs coverage** counts are zero. On a wide screen, Progress also shows **Review corpus — mapped**. For Concept or Style, every imported image has an intentional **Accept** or **Reject** decision; those dataset types do not show the Progress checklist.
