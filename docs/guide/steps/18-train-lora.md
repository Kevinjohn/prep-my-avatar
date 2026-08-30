# Step 18: Train a LoRA

Training turns the kept images and captions into a `.safetensors` LoRA for one model family. This optional step can use configured local ai-toolkit or a vast.ai cloud worker.

## Before you begin

Training can take significant time, disk space, GPU memory, and—for cloud runs—money. Complete curation, captions, leak review, and source-rights confirmation. Accept any required base-model licence and add its Hugging Face token before launch.

## Do this

1. Open **Training** in the dataset sidebar.
2. Choose the LoRA family that matches the target model you intend to use.
3. Read the readiness summary and resolve blocking findings.
4. Keep the automatic step count and default recipe for a first run. Open **Advanced options** only when you understand the setting you need to change.
5. Select **Train the LoRA** for the configured local trainer, or **Train in cloud**.
6. Read the **Before training** confirmation. Fix duplicate pairs or caption leaks shown there.
7. Confirm the launch. For cloud training, check the quoted limits before accepting.
8. Keep the app running for local training. Follow either type of run from **Runs**.

## You are finished when

The run reaches **Finished** and at least one checkpoint appears. If it fails, open the run log, keep the exact error, fix that cause, and use retry rather than starting several duplicate cloud jobs.
