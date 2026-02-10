# Deploying to PythonAnywhere

Step-by-step guide to getting the SharePoint crawler running on PythonAnywhere
(Hacker tier or above — required for unrestricted outbound HTTP).

## Step 1: Upload the Project

**Option A — Git (recommended)**

If you've pushed this project to a Git repo:

```bash
# Open a Bash console on PythonAnywhere
cd ~
git clone https://github.com/your-org/sp-crawler.git
cd sp-crawler
```

**Option B — Manual Upload**

1. Go to the **Files** tab in PythonAnywhere
2. Navigate to `/home/yourusername/`
3. Create a new directory: `sp-crawler`
4. Upload all project files into that directory

## Step 2: Set Up a Virtual Environment

PythonAnywhere provides Python 3.10+ by default. Create an isolated
environment for the project:

```bash
cd ~/sp-crawler
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Step 3: Configure Environment Variables

Create your `.env` file:

```bash
cp .env.example .env
nano .env
```

Fill in your Azure AD credentials and SharePoint site URL:

```
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-secret-value-here
SP_SITE_URL=https://yourtenant.sharepoint.com/sites/MosaicDataSolutions
```

Save and exit (`Ctrl+X`, then `Y`, then `Enter` in nano).

## Step 4: Test the Connection

```bash
cd ~/sp-crawler
source venv/bin/activate
python main.py --test
```

You should see:
```
Step 1: Acquiring access token...
  Token acquired successfully
Step 2: Resolving SharePoint site...
  Site name: Mosaic Data Solutions
  ...
CONNECTION TEST PASSED
```

If you get connection errors, verify:
- Your PythonAnywhere account is a paid tier (free accounts block Graph API)
- Your Azure AD app has admin consent granted
- Your client secret hasn't expired

## Step 5: Run the Crawl

```bash
cd ~/sp-crawler
source venv/bin/activate
python main.py --output ./output
```

Output files will be saved to `~/sp-crawler/output/`.

## Step 6: Download Results

1. Go to the **Files** tab in PythonAnywhere
2. Navigate to `/home/yourusername/sp-crawler/output/`
3. Click on each file to download:
   - `sp_crawl_YYYYMMDD_HHMMSS.csv`
   - `sp_crawl_YYYYMMDD_HHMMSS.json`
   - `sp_structure_YYYYMMDD_HHMMSS.txt`

## Setting Up Scheduled Crawls (Optional)

PythonAnywhere supports scheduled tasks — useful for running the crawler
on a regular basis (daily, weekly) to track changes over time.

1. Go to the **Tasks** tab in PythonAnywhere
2. Add a new scheduled task:
   - **Command**: `/home/yourusername/sp-crawler/venv/bin/python /home/yourusername/sp-crawler/main.py --output /home/yourusername/sp-crawler/output`
   - **Frequency**: Daily or as needed
3. The task will run and save timestamped output files

**Important**: Use absolute paths in scheduled tasks since they don't
run from your project directory.

## File Storage on PythonAnywhere

PythonAnywhere storage notes:
- **Hacker tier**: 5 GB disk space
- Crawl outputs are small (a few MB even for thousands of documents)
- Old crawl results accumulate over time — periodically download and clean up
- For long-term storage, consider pushing results to Azure Blob Storage
  (a future enhancement)

## Troubleshooting

### "Connection refused" or timeout errors
Your account may be on the free tier. Graph API (`graph.microsoft.com`)
requires a paid PythonAnywhere account for outbound access.

### "ModuleNotFoundError" in scheduled tasks
Make sure the scheduled task command uses the full path to the venv Python:
`/home/yourusername/sp-crawler/venv/bin/python`

### Token acquisition fails
Check that your Azure AD client secret hasn't expired. Secrets created
with a 12-month expiry will need to be rotated.

### Crawl runs but finds 0 documents
- Verify the SP_SITE_URL points to the correct site
- Check that the Azure AD app has `Sites.Read.All` and `Files.Read.All`
  permissions with admin consent
- Try `--verbose` flag to see detailed debug output
