# Mendeley Library Tools

Scripts to automatically organise and enrich an academic reference library in Mendeley. Built for a Master's dissertation on parametric prosthetic design.

**What these scripts do:**
- **Organiser** — reads your local PDF folders and creates matching folders in Mendeley, then assigns each paper to the right folder automatically
- **Enricher** — looks up each paper online (via CrossRef) and fills in missing metadata (authors, year, abstract, journal) both in Mendeley and inside the PDF files themselves

---

## Before You Start

You will need three things installed on your computer:

1. **Python 3.10 or newer** — [download here](https://www.python.org/downloads/)
2. **uv** — a Python tool installer (faster and simpler than pip)
3. **A Mendeley API app** — a one-time registration so the scripts can talk to your Mendeley account

---

## Step 1 — Install uv

Open a **Terminal** (on Mac: `Terminal.app`; on Windows: `Command Prompt` or `PowerShell`) and paste this command:

**Mac / Linux:**
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your terminal after installing.

---

## Step 2 — Install the Mendeley tools

In your terminal, run these two commands one at a time:

```
uv tool install mendeley-mcp
```

```
uv tool run --with pymupdf python --version
```

If you see a Python version number printed (e.g. `Python 3.12.3`), the installation worked.

---

## Step 3 — Register a Mendeley API app

This is a one-time setup so the scripts can access your Mendeley library.

1. Go to [dev.mendeley.com/myapps.html](https://dev.mendeley.com/myapps.html) and sign in with your Mendeley/Elsevier account
2. Click **"Register a new app"**
3. Fill in any name (e.g. `My Library Tools`) and description
4. Set the **Redirect URL** to exactly: `http://localhost:8585/callback`
5. Select **"Authorization code"** as the flow (not Legacy)
6. Click **Register** — you will see a **Client ID** and **Client Secret**. Keep this page open.

---

## Step 4 — Connect to your Mendeley account

In your terminal, run:

```
mendeley-auth login
```

It will ask for your **Client ID** and **Client Secret** (from Step 3), then open your browser to authorise the connection. After you approve it, you can close the browser — the credentials are saved securely on your computer.

To check the connection worked:

```
mendeley-auth status
```

You should see your name printed.

---

## Step 5 — Download the scripts

Click the green **"Code"** button on this page and choose **"Download ZIP"**. Unzip it anywhere on your computer.

Or, if you have Git installed:

```
git clone https://github.com/pedrocandeias/mendeley-tools.git
```

---

## Running the Scripts

Open your terminal and navigate to the folder where you unzipped the scripts:

```
cd /path/to/mendeley-tools
```

> **Tip:** On Mac, you can drag the folder onto the terminal window after typing `cd ` (with a space) to fill in the path automatically.

---

### Script 1 — Organiser

This script creates folders in Mendeley and assigns your papers to them.

**Always do a preview first** (this makes no changes):

```
python mendeley_organizer.py
```

Read through the output. It shows which papers it found and which folders it would create. When you're happy:

```
python mendeley_organizer.py --apply
```

Done — check Mendeley to see your new folders.

---

### Script 2 — Enricher

This script looks up missing metadata for your papers (authors, year, abstract, journal) and updates both Mendeley and the PDF files.

**Preview first:**

```
python mendeley_enrich.py
```

Then apply:

```
python mendeley_enrich.py --apply
```

> **Note:** This queries the CrossRef database for each paper. It takes a few minutes if you have many papers. Do not close the terminal while it runs.

---

## Folder Mapping

The organiser maps your local PDF folders to folders in Mendeley:

| Your local folder | Mendeley folder created |
|---|---|
| `prosthetics-design` | Design de Próteses |
| `3dprinting-prosthetics` | Impressão 3D em Próteses |
| `antropometria` | Antropometria |
| `amputacao` | Amputação |
| `reabilitacao` | Reabilitação |
| `parametrico` | Modelação Paramétrica |
| `prosthetics-user` | Utilizador de Próteses |
| `colaboracao` | Colaboração e Co-design |
| `prosthetics-control` | Controlo de Próteses |
| `outros` | Outros |
| `lower-limb` | Membro Inferior |
| `normas` | Normas |

---

## Troubleshooting

**"command not found: mendeley-auth"**
Close and reopen your terminal after installing uv, then try again.

**"No credentials found"**
Run `mendeley-auth login` and follow the steps again.

**"401 Unauthorized"**
Your session expired. Run `mendeley-auth login` to reconnect.

**A paper wasn't matched or enriched**
See `titles_to_fix.txt` — unmatched and unenriched papers are listed there with notes on what to fix manually.

**The script stops with an error**
Copy the error message and open an issue on this repository.

---

## Other Files

| File | What it does |
|---|---|
| `titles_to_fix.txt` | List of papers with title issues to fix manually |
| `flag_titles.py` | Scans PDF filenames and flags problems (run before the organiser) |
| `rename_pdfs.py` | Renames PDFs using their metadata |

---

## Privacy

All data goes directly between your computer and Mendeley's servers (`api.mendeley.com`). CrossRef is also queried directly. No third-party services are involved. Your credentials are stored in your operating system's secure keychain (macOS Keychain, Windows Credential Manager, or Linux Secret Service).
