# Step 1: Open Prep My Avatar

Prep My Avatar runs on your computer and opens in a web browser. You do not need an API key, a graphics card, or any AI tools to open it and begin reviewing photos.

## Before you begin

You need a Windows, macOS, or Linux computer and an internet connection for the first installation. Keep five or more clear photos ready for your first test. Use photos you own or have permission to process.

On macOS or Linux, install [Python](https://www.python.org/downloads/) before continuing. Python 3.10 can run the core app. If you may install the optional machine-learning tools, use Python 3.11 or 3.12. Open Terminal and run `python3 --version`. If Terminal says the command was not found, install Python 3.11 or 3.12, close and reopen Terminal, then run the check again. If `python3` reports another version after you installed one of those, run the matching `python3.11 --version` or `python3.12 --version`, then replace `python3 -m venv .venv` below with that matching command—for example, `python3.11 -m venv .venv`.

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

Your browser shows the **Setup** screen. On first launch, choose **Start setup** to configure tools now. The next five pages explain its five screens one at a time.

Setup is optional as a whole: **Skip setup — I'll do it later** takes you directly to **Datasets**. If you start Setup, its local-vision screen must be ready before the wizard can advance; Step 4 explains that choice exactly.

If the page does not open, keep the terminal visible and use the error message with the **Troubleshooting** reference in this guide.
