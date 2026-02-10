# Azure AD App Registration Setup

This guide walks you through creating the Azure AD (Entra ID) app registration
needed for the SharePoint crawler to authenticate and access your SharePoint
Online site.

## Prerequisites

- Global Admin or Application Administrator role in your Microsoft 365 tenant
- Access to the Azure Portal (https://portal.azure.com)

## Step 1: Create the App Registration

1. Go to **Azure Portal** > **Microsoft Entra ID** > **App registrations**
2. Click **New registration**
3. Fill in:
   - **Name**: `SP Document Crawler` (or whatever you prefer)
   - **Supported account types**: "Accounts in this organizational directory only"
   - **Redirect URI**: Leave blank (not needed for this app)
4. Click **Register**
5. On the overview page, copy and save:
   - **Application (client) ID** → this is your `AZURE_CLIENT_ID`
   - **Directory (tenant) ID** → this is your `AZURE_TENANT_ID`

## Step 2: Create a Client Secret

1. In your app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Add a description: `SP Crawler Secret`
4. Choose expiration (recommend 12 months for pilot)
5. Click **Add**
6. **Immediately copy the secret value** → this is your `AZURE_CLIENT_SECRET`
   (you won't be able to see it again)

## Step 3: Add API Permissions

1. Go to **API permissions** > **Add a permission**
2. Select **Microsoft Graph**
3. Select **Application permissions** (not Delegated)
4. Add these permissions:
   - `Sites.Read.All` — read all site collections
   - `Files.Read.All` — read all files in all site collections
5. Click **Add permissions**
6. Click **Grant admin consent for [Your Org]** (requires admin role)
7. Verify all permissions show a green checkmark under "Status"

## Step 4: Configure Your .env File

Copy `.env.example` to `.env` and fill in your values:

```
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-secret-value-here
SP_SITE_URL=https://yourtenant.sharepoint.com/sites/MosaicDataSolutions
```

## Finding Your SharePoint Site URL

Your site URL follows this pattern:
`https://[tenant].sharepoint.com/sites/[SiteName]`

To find it:
1. Navigate to your SharePoint site in a browser
2. The URL in your address bar is your site URL
3. Remove any trailing paths (like `/Shared Documents/...`)

## Verifying the Setup

Run the crawler with the `--test` flag to verify authentication:

```bash
python main.py --test
```

This will attempt to connect and list the document libraries on your site
without crawling any documents.

## Security Notes

- Never commit your `.env` file to source control
- The `.gitignore` file in this project excludes `.env` by default
- Rotate the client secret before it expires
- For production use, consider Azure Key Vault instead of `.env` files
- The `Sites.Read.All` and `Files.Read.All` permissions are read-only —
  this app cannot modify or delete anything in SharePoint
