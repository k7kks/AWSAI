# Kiro Registration Manager

This tool integrates the AWS Builder ID registration machine into the Kiro system, automating the process of creating and configuring AWS Builder ID accounts for use with Kiro.

## Features

- Automated Outlook email activation
- AWS Builder ID registration with browser automation
- Offline verification code retrieval via Microsoft Graph API
- SSO token extraction and conversion to Kiro-compatible credentials
- Credential storage in JSON format

## Prerequisites

1. Python 3.8+
2. Playwright with Chromium browser installed
3. Microsoft Graph API access (refresh token and client ID)

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
python -m playwright install chromium
```

## Usage

### Single Account Registration

```bash
python tools/register_manager.py \
  --email your-email@outlook.com \
  --password your-password \
  --refresh-token your-microsoft-refresh-token \
  --client-id your-microsoft-client-id
```

### Batch Registration

Create a JSON file with account details:

```json
[
  {
    "email": "account1@outlook.com",
    "password": "password123",
    "refresh_token": "M.C509_BAY.0.U.-CgNktq...",
    "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
  },
  {
    "email": "account2@outlook.com",
    "password": "password456",
    "refresh_token": "M.C509_BAY.0.U.-CgNktq...",
    "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d754"
  }
]
```

Then run:

```bash
python tools/register_manager.py \
  --accounts-file accounts.json \
  --concurrency 2
```

## How It Works

1. **Outlook Activation**: Automates the email activation process using Playwright
2. **AWS Registration**: Registers the AWS Builder ID account and handles verification
3. **Code Retrieval**: Uses Microsoft Graph API to fetch verification codes from emails
4. **Token Conversion**: Converts AWS SSO tokens to Kiro-compatible credentials
5. **Storage**: Saves credentials in `configs/kiro/{timestamp}_kiro-auth-token/auth.json`

## Output Format

The tool generates credentials in the following JSON format:

```json
{
  "accessToken": "aoaAAAA...",
  "refreshToken": "aorAAAA...",
  "clientId": "e8pqSrALVjvbqaW...",
  "clientSecret": "eyJraWQiOiJrZXktMTU2NDAy...",
  "expiresAt": "2026-01-19T06:23:51.312Z",
  "authMethod": "builder-id",
  "region": "us-east-1"
}
```

## Security Notes

- Store refresh tokens securely - they provide access to email accounts
- Use minimal required permissions for Microsoft Graph API (Mail.Read only)
- Credentials are saved locally - implement proper storage for production use

## Integration with Kiro

The generated credentials can be used to authenticate with Kiro's AI services. The auth.json files are stored in the `configs/kiro/` directory and can be loaded by the Kiro system as needed.