# Step 13: Generate missing views

Generation is optional. Use it only for real coverage gaps that you cannot fill with suitable source photos. Generated images are candidates and never enter training until you accept them.

This guided gap generator is Character-only. Concept and Style datasets do not show it; add more examples with **Import**, or use the Concept scraper when appropriate, then continue to curation.

## Before you begin

You need a tested Gemini, Replicate, or OpenAI credential, or a working local Klein setup. Before remote generation, explicitly enable remote-generation privacy in **Settings → Image engines**. Remote providers may charge per request and receive the prompt plus the bounded anchor pack.

## Do this

1. In **Coverage plan**, select **Review gap shots**, or open the generation panel under **Add images**.
2. Review the recommended shots. Remove any shot you do not actually need.
3. Choose the configured engine and model.
4. Keep the multiplier at one for the first attempt.
5. Read the estimated request count and cost information.
6. Start generation and wait for the results. Use **Stop generation** if early results show that the prompt or identity is wrong.
7. Use the edit control on an individual result to correct its prompt and regenerate that shot only.

## You are finished when

For Character, every requested generation has completed or been stopped and each result awaits review. For Concept or Style, the step is finished after you deliberately use import or the Concept scraper instead.
