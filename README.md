## Repository Overview

This project provides a CLI tool to import Gmail Takeout `.mbox` exports into Freshdesk as tickets—grouped by conversation, tagged, assigned to an “Imported” group, and safely resumable across runs.

## Features

* **Thread grouping** via Gmail’s `X-GM-THRID`
* **Spam & trash filtering** using Gmail labels and auto-response headers
* **HTML & plain-text support** preserving message formatting
* **Custom date field** storing original sent date
* **Imported-group assignment** and `"imported"` tag
* **Resume-safe** with SQLite progress tracking and purge prompt
* **Exponential back-off retries** via Tenacity
* **Optional progress bar** with ETA (requires `tqdm`)

---

## Getting Started

### 1. Clone the Repo

```bash
git clone https://github.com/your-org/freshdesk-mbox-importer.git
cd freshdesk-mbox-importer
```

### 2. Python Environment

Create and activate a virtualenv (Python 3.10+):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration

Copy and populate your environment variables:

```bash
cp .env.sample .env
```

Edit `.env` and fill in:

```dotenv
# Freshdesk API
FD_DOMAIN=yourcompany.freshdesk.com
FD_KEY=your_api_key

# Freshdesk custom date field name (e.g. cf_original_email_date)
ORIGINAL_DATE_FIELD=cf_original_email_date

# Name of the Freshdesk group to assign imported tickets
IMPORT_GROUP_NAME=Imported

# Your mailbox owner email for outgoing message handling
MBOX_OWNER_EMAIL=you@example.com

# Path to your Takeout mbox (default: takeout.mbox in repo root)
MBOX_PATH=takeout.mbox

# Delay between API calls (in seconds)
RATE_DELAY=0.5
```

### 4. Prepare Your MBOX

Place your Google Takeout export at the repo root:

```
freshdesk-mbox-importer/
├── takeout.mbox
├── .env
├── ...
```

### 5. Initial Setup

On first run you’ll be prompted:

* **Purge progress database?** Choose **Yes** if this is a fresh mbox import; otherwise **No** to resume.
* **Create “Imported” group** in Freshdesk (if missing), then press Enter to continue.

### 6. Run the Import

With your virtualenv active:

```bash
python -m freshdesk_mbox_importer run
```

* You’ll see a progress bar (if `tqdm` is installed).
* **Ctrl-C** will safely save progress; re-running resumes where you left off.
* On completion, the SQLite DB is removed so a new import can start fresh.

---

## Advanced Usage

* **Skip progress prompt** by setting environment: `PURGE_DB=yes python -m freshdesk_mbox_importer run`
* **Disable progress bar** by uninstalling `tqdm` or setting `TQDM_DISABLE=true`.
* **Adjust retry behavior** by editing the `@retry` decorator parameters.

---

## Troubleshooting

* **400 Bad Request**: Ensure `ORIGINAL_DATE_FIELD` matches an existing custom date field in Admin → Workflows → Ticket Fields.
* **Group not found**: Create the group named exactly as `IMPORT_GROUP_NAME` under Admin → Groups.
* **Slow startup**: First run reads the entire mbox. Subsequent runs resume quickly via SQLite.

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/xyz`)
3. Commit your changes
4. Open a Pull Request

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
