# Step 1: Open Prep My Avatar

Prep My Avatar runs on your computer and opens in a web browser. You do not need an API key, a graphics card, or any AI tools to open it and begin reviewing photos.

## Before you begin

You need a Windows, macOS, or Linux computer and an internet connection for the first installation. Keep five or more clear photos ready for your first test. Use photos you own or have permission to process.

## Do this

### Windows

1. Download or clone the repository and extract it if it arrived as a ZIP file.
2. Open the extracted `prep-my-avatar` folder.
3. Double-click `start.bat`.
4. Leave the terminal window open while you use the app.

### macOS or Linux

1. Open the Terminal application.
2. Type `cd `, including the space, drag the `prep-my-avatar` folder into the Terminal window, and press Enter.
3. Run these commands one line at a time:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/source_launcher.py --install --root . --data-dir data
python data/source-launcher.py --root . --data-dir data
```

4. Leave Terminal open. Open <http://127.0.0.1:5050/> if the browser does not open automatically.

The repository README has the canonical [Installation and launch](https://github.com/Kevinjohn/prep-my-avatar#installation-and-launch) instructions, including later launches and Docker.

## You are finished when

Your browser shows **Welcome to Prep My Avatar** or the **Setup** screen. On first launch, choose **Start setup**. All five setup steps are optional; the next five pages explain them one at a time.

If the page does not open, keep the terminal visible and use the error message with the **Troubleshooting** reference in this guide.
