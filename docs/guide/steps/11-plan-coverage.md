# Step 11: Check photo variety

Photo variety means the different views and conditions in your accepted images: face, bust, body, and back views, plus differences in angle, expression, lighting, pose, and background.

This is a Character-only step. Concept and Style datasets go directly from **Review photos** to **Curate images** because they do not need this view-by-view check.

## Before you begin

Finish describing and accepting the imported photos first. A photo without these details is shown as **unknown**; unknown does not mean the view is missing.

## Do this

1. Open **Check photo variety** in the dataset step navigator. Its URL ends in `/coverage`.
2. Choose **Local settings**, **OpenAI API**, or **Google Gemini API**, then select **Analyse photo variety**. Remote choices name the destination and require confirmation before any image leaves the machine.
   - If no photo details are added, verify the selected model and credential in **Settings** and retry. Describe photos manually only when the selected provider still cannot classify them; never treat an empty result as completed analysis.
3. Record framing, angle, expression, lighting, pose, background, and occlusion where the app asks for them.
4. Keep **Balanced** for a normal first run. **Strict** recommends fewer generated gaps; **Experimental** allows more.
5. Read each framing card. The first number is what you have and the second is the target.
6. Expand the other dimensions to see weak, missing, covered, and unknown evidence.
7. Adjust a target only when your intended output genuinely needs a different balance.
8. Select **Save targets** after changing the profile or any number.
9. Add another real photo whenever practical. Treat generated gap shots as optional supplements, not replacements for unknown imports.
10. Select **Continue to Set primary reference**.

## You are finished when

You understand which kinds of photos are missing, every accepted image has its details recorded, and the selected profile is saved. The step navigator marks **Check photo variety — Complete**. Concept and Style navigators omit this Character-only page.
