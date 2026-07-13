# Deployment Manual — RTF-to-PDF Compiler

This guide describes how to deploy the RTF-to-PDF Compiler on a Windows PC that has **no Python, no LibreOffice, and no Git** installed. The application is pulled directly from Git, and updates are applied with a simple `git pull`.

## 1. Overview

The RTF-to-PDF Compiler is a locally hosted web application. It converts a directory of RTF files into a single merged PDF with bookmarks, a table of contents, headers/footers, and page numbering. Once started, it is used through a web browser at `http://localhost:5000`. All processing happens on the local machine; no internet access is required at runtime.

## 2. Prerequisites (one-time, requires admin rights)

Install the following, in this order, with default settings unless noted:

| # | Software | Source | Notes |
|---|----------|--------|-------|
| 1 | **Git for Windows** | https://git-scm.com/download/win | Accept all defaults. |
| 2 | **Python 3.12 (64-bit)** | https://www.python.org/downloads/ | **Python 3.12 or newer is required.** On the first installer screen, tick **"Add python.exe to PATH"**. |
| 3 | **LibreOffice** (current stable) | https://www.libreoffice.org/download/ | Install to the default location (`C:\Program Files\LibreOffice`). A full default install is required — the application uses LibreOffice's conversion engine and its bundled Python. |

## 3. Install the application

Open a **Command Prompt** and run:

```bat
git clone https://github.com/julesvdz/rtftosinglepdf.git C:\rtftosinglepdf
cd C:\rtftosinglepdf
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

This clones the code, creates an isolated Python environment in `C:\rtftosinglepdf\.venv`, and installs the required packages (Flask, PyMuPDF, striprtf, Werkzeug, openpyxl).

> Keep the install path short (e.g. `C:\rtftosinglepdf`). LibreOffice creates deeply nested working folders, and long base paths can hit Windows path-length limits.

## 4. Run the application

```bat
cd C:\rtftosinglepdf
.venv\Scripts\activate
python app.py
```

Then open **http://localhost:5000** in a browser.

- Keep the console window open while using the tool; closing it stops the application.
- The **first conversion after startup is slower** — LibreOffice creates its user profiles on first use. Subsequent jobs are faster.
- The **output directory must be writable**; it receives only the deliverables: the final PDF, the process log, `config.json`, and a copy of the CSV mapping (if used). The RTF input directory is only read from.
- All processing happens in a **local temporary folder** under `%LOCALAPPDATA%\Temp\rtf2pdf\job_*` — its exact path is recorded in the process log, and it is removed automatically when the job ends (also on failure). Leftovers from a crashed run are cleaned up the next time the application starts.
- The server listens on **all network interfaces, port 5000**, so other PCs on the LAN can reach it at `http://<pc-name>:5000`. If this is not wanted, block port 5000 in Windows Firewall (or allow it if LAN access is desired, per site policy).

## 4a. Data on network shares

The RTF input directory and the output directory may be on a network fileshare (a mapped drive letter such as `Z:\...` or a UNC path such as `\\server\share\...`). This is fully supported: each source RTF is copied once to the local temporary folder before conversion, all intermediate work (per-section PDFs, LibreOffice profiles, PDF assembly) is done on local disk, and only the final deliverables are written back to the share. Note that a mapped drive letter is only visible to the user session that mapped it — if the app is ever run under a different account (e.g. a scheduled task), use the UNC path instead.

## 5. Update to the latest version

With the application **stopped**, run:

```bat
cd C:\rtftosinglepdf
git pull
.venv\Scripts\activate
pip install -r requirements.txt
```

Then start the application again as in section 4.

## 6. Verify the installation (smoke test)

1. Start the application (section 4) and open `http://localhost:5000` — the UI should load.
2. Point it at a small folder containing a few RTF files and run a job.
   (Note: the repository does not include sample RTF files — use your own test set.)
3. Confirm the job completes and the merged, bookmarked PDF downloads and opens correctly.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Job fails with `RuntimeError: LibreOffice (soffice) not found` | LibreOffice is not installed, or installed to a non-standard location. Install to `C:\Program Files\LibreOffice`, or add its `program` folder to the system `PATH`. |
| `TypeError` mentioning `rmtree` / `onexc` | Python is older than 3.12. Install Python 3.12+ and recreate the venv (delete `.venv`, repeat section 3 from `python -m venv .venv`). |
| Browser cannot connect to `http://localhost:5000` | The console window was closed, or port 5000 is in use by another program. Restart the app and check the console for errors. |
| First job appears to hang for a minute | Normal: LibreOffice profile creation on first launch. Wait — later jobs are fast. |
| Errors deleting/creating working folders, or path-related failures | Base paths too long. Use short input/output paths, or enable Windows long-path support (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled` = 1). |
| `git pull` reports local changes and refuses to update | Files under `C:\rtftosinglepdf` were edited locally. Revert them (`git checkout -- .`) or contact the maintainer. |
