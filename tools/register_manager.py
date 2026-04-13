"""
Kiro AWS Builder ID Registration Manager

This tool automates the registration of AWS Builder ID accounts and integrates
them with the Kiro system. Based on the Kiro registration machine technical analysis.

Features:
- Automated Outlook email activation
- AWS Builder ID registration using Playwright
- Offline verification code retrieval via Microsoft Graph API
- SSO token extraction and conversion to Kiro-compatible credentials
- Credential storage and management

Dependencies to add to requirements.txt:
- playwright==1.40.0
- requests-oauthlib==1.3.1
- python-dotenv==1.0.0
"""

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from playwright.async_api import async_playwright


class RegistrationManager:
    """Manages AWS Builder ID registration process"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.configs_dir = base_dir / "configs" / "kiro"
        self.configs_dir.mkdir(parents=True, exist_ok=True)

        # Microsoft Graph API endpoints
        self.token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        self.graph_url = "https://graph.microsoft.com/v1.0/me/messages"

        # AWS endpoints
        self.oidc_register_url = "https://oidc.us-east-1.amazonaws.com/client/register"
        self.device_auth_url = "https://oidc.us-east-1.amazonaws.com/device_authorization"
        self.token_exchange_url = "https://oidc.us-east-1.amazonaws.com/token"

        # AWS senders for verification emails
        self.aws_senders = [
            'no-reply@signin.aws',
            'no-reply@login.awsapps.com',
            # Add more if needed
        ]

        # Verification code patterns
        self.code_patterns = [
            r'(?:verification\s*code|验证码|Your code is)[：:\s]*(\d{6})',
            r'^\s*(\d{6})\s*$',  # Standalone 6-digit number
            r'>\s*(\d{6})\s*<',  # Between HTML tags
        ]

    async def register_account(self, email: str, password: str, refresh_token: str, client_id: str) -> Dict:
        """
        Register a single AWS Builder ID account

        Args:
            email: Outlook email address
            password: Account password
            refresh_token: Microsoft OAuth2 refresh token
            client_id: Microsoft Graph API client ID

        Returns:
            Dict containing registration results and credentials
        """
        print(f"Starting registration for {email}")

        # Store tokens for use in other methods
        self.current_refresh_token = refresh_token
        self.current_client_id = client_id

        # Step 1: Activate Outlook email
        await self._activate_outlook_email(email, password)

        # Step 2: Register AWS Builder ID
        sso_token = await self._register_aws_builder_id(email, password)

        # Step 3: Convert SSO token to Kiro credentials
        kiro_creds = await self._convert_sso_to_kiro_credentials(sso_token)

        # Step 4: Save credentials
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        config_dir = self.configs_dir / f"{timestamp}_kiro-auth-token"
        config_dir.mkdir(exist_ok=True)

        config_file = config_dir / "auth.json"
        with open(config_file, 'w') as f:
            json.dump(kiro_creds, f, indent=2)

        print(f"Registration completed for {email}")
        return {
            "email": email,
            "sso_token": sso_token,
            "kiro_credentials": kiro_creds,
            "config_path": str(config_file)
        }

    async def _activate_outlook_email(self, email: str, password: str) -> None:
        """
        Activate Outlook email account
        This involves visiting Microsoft activation page and completing setup

        Note: This is a placeholder implementation. Actual activation flow may vary.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # Visible for debugging
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to Outlook login page
                await page.goto("https://login.live.com/")

                # Wait for email input
                await page.wait_for_selector('input[type="email"]')
                await page.fill('input[type="email"]', email)
                await page.click('input[type="submit"]')

                # Wait for password input
                await page.wait_for_selector('input[type="password"]')
                await page.fill('input[type="password"]', password)
                await page.click('input[type="submit"]')

                # Handle potential security prompts (2FA, etc.)
                # This may require additional handling based on account setup

                # Check if activation is required
                # Look for activation prompts and complete them

                print(f"Outlook activation completed for {email}")

            except Exception as e:
                print(f"Outlook activation failed for {email}: {e}")
                raise
            finally:
                await browser.close()

    async def _register_aws_builder_id(self, email: str, password: str) -> str:
        """
        Register AWS Builder ID using Playwright automation

        Returns:
            SSO authentication token
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to AWS Builder ID registration
                await page.goto("https://signin.aws.amazon.com/signin?client_id=arn:aws:iam::015428540659:user%2Fhomepage&redirect_uri=https%3A%2F%2Fconsole.aws.amazon.com%2Fconsole%2Fhome%3Fstate%3DhashArgs%23%26isauthcode%3Dtrue&response_type=code&state=hashArgs")

                # Wait for and click "Create AWS Builder ID" or similar
                await page.wait_for_selector('text="Create AWS Builder ID"', timeout=10000)
                await page.click('text="Create AWS Builder ID"')

                # Fill email
                await page.wait_for_selector('input[type="email"]')
                await page.fill('input[type="email"]', email)

                # Click continue
                await page.click('input[type="submit"]')

                # Wait for verification code input
                await page.wait_for_selector('input[name="code"]', timeout=30000)

                # Get verification code from email
                # This would need the refresh_token and client_id passed to this method
                # For now, assume we have them from the main method
                verification_code = self._get_verification_code(self.current_refresh_token, self.current_client_id)

                if not verification_code:
                    raise Exception("Failed to retrieve verification code")

                # Enter verification code
                await page.fill('input[name="code"]', verification_code)

                # Click verify
                await page.click('input[type="submit"]')

                # Set password
                await page.wait_for_selector('input[type="password"]')
                await page.fill('input[type="password"]', password)
                await page.fill('input[name="confirmPassword"]', password)

                # Complete registration
                await page.click('input[type="submit"]')

                # Wait for completion and extract SSO token
                await page.wait_for_timeout(5000)  # Wait for redirects

                cookies = await context.cookies()
                sso_token = None
                for cookie in cookies:
                    if cookie['name'] == 'x-amz-sso_authn':
                        sso_token = cookie['value']
                        break

                if not sso_token:
                    raise Exception("Failed to extract SSO token")

                print(f"AWS Builder ID registration completed for {email}")
                return sso_token

            except Exception as e:
                print(f"AWS registration failed for {email}: {e}")
                raise
            finally:
                await browser.close()

    def _get_verification_code(self, refresh_token: str, client_id: str) -> Optional[str]:
        """
        Get verification code from email using Microsoft Graph API

        Args:
            refresh_token: Microsoft OAuth2 refresh token
            client_id: Microsoft Graph API client ID

        Returns:
            6-digit verification code or None if not found
        """
        # Exchange refresh token for access token
        token_data = {
            'client_id': client_id,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }

        token_response = requests.post(self.token_url, data=token_data)
        token_response.raise_for_status()
        access_token = token_response.json()['access_token']

        # Get recent emails
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'$top': 50, '$orderby': 'receivedDateTime desc'}

        messages_response = requests.get(self.graph_url, headers=headers, params=params)
        messages_response.raise_for_status()
        messages = messages_response.json()['value']

        # Find AWS verification email
        for message in messages:
            sender = message['from']['emailAddress']['address'].lower()
            if sender in [s.lower() for s in self.aws_senders]:
                subject = message['subject'].lower()
                if 'verification' in subject or 'code' in subject or '验证码' in subject:
                    # Get message body
                    body = message.get('body', {}).get('content', '')

                    # Search for verification code
                    for pattern in self.code_patterns:
                        match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
                        if match:
                            code = match.group(1)
                            # Validate it's exactly 6 digits
                            if re.match(r'^\d{6}$', code):
                                return code

        return None

    async def _convert_sso_to_kiro_credentials(self, sso_token: str) -> Dict:
        """
        Convert AWS SSO token to Kiro-compatible credentials

        Args:
            sso_token: AWS SSO authentication token

        Returns:
            Dict with accessToken, refreshToken, clientId, etc.
        """
        # Register OIDC client
        register_data = {
            'clientName': 'Kiro IDE',
            'clientType': 'public',
            'scopes': [
                'codewhisperer:completions',
                'codewhisperer:analysis',
                # Add other required scopes
            ]
        }

        register_response = requests.post(self.oidc_register_url, json=register_data)
        register_response.raise_for_status()
        client_data = register_response.json()

        # Initiate device authorization
        device_data = {
            'clientId': client_data['clientId'],
            'clientSecret': client_data['clientSecret'],
            'startUrl': 'https://view.awsapps.com/start'
        }

        device_response = requests.post(self.device_auth_url, json=device_data)
        device_response.raise_for_status()
        device_info = device_response.json()

        # Poll for token
        max_attempts = 60  # 2 minutes
        for attempt in range(max_attempts):
            token_data = {
                'clientId': client_data['clientId'],
                'clientSecret': client_data['clientSecret'],
                'deviceCode': device_info['deviceCode'],
                'grantType': 'urn:ietf:params:oauth:grant-type:device_code'
            }

            token_response = requests.post(self.token_exchange_url, json=token_data)
            if token_response.status_code == 200:
                token_info = token_response.json()
                break
            elif token_response.status_code == 400:
                error = token_response.json().get('error')
                if error == 'authorization_pending':
                    time.sleep(2)  # Wait 2 seconds before retrying
                    continue
                else:
                    raise Exception(f"Token exchange failed: {error}")
            else:
                token_response.raise_for_status()
        else:
            raise Exception("Token polling timed out")

        # Return Kiro-compatible credentials
        return {
            'accessToken': token_info['accessToken'],
            'refreshToken': token_info['refreshToken'],
            'clientId': client_data['clientId'],
            'clientSecret': client_data['clientSecret'],
            'expiresAt': (datetime.now() + timedelta(seconds=token_info.get('expiresIn', 3600))).isoformat(),
            'authMethod': 'builder-id',
            'region': 'us-east-1'
        }


def main():
    parser = argparse.ArgumentParser(description="Kiro AWS Builder ID Registration Manager")
    parser.add_argument("--email", help="Outlook email address")
    parser.add_argument("--password", help="Account password")
    parser.add_argument("--refresh-token", help="Microsoft OAuth2 refresh token")
    parser.add_argument("--client-id", help="Microsoft Graph API client ID")
    parser.add_argument("--accounts-file", help="JSON file containing list of accounts to register")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent registrations")

    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    manager = RegistrationManager(base_dir)

    async def run_registrations():
        if args.accounts_file:
            # Batch registration from file
            with open(args.accounts_file, 'r') as f:
                accounts = json.load(f)

            semaphore = asyncio.Semaphore(args.concurrency)
            tasks = []

            async def register_with_semaphore(account):
                async with semaphore:
                    return await manager.register_account(
                        account['email'],
                        account['password'],
                        account['refresh_token'],
                        account['client_id']
                    )

            for account in accounts:
                task = register_with_semaphore(account)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"Registration failed for account {i}: {result}")
                else:
                    print(f"Registration succeeded for {result['email']}")

        elif args.email and args.password and args.refresh_token and args.client_id:
            # Single registration
            result = await manager.register_account(
                args.email,
                args.password,
                args.refresh_token,
                args.client_id
            )
            print(f"Registration completed: {result}")
        else:
            parser.error("Either provide --accounts-file or all individual account parameters")

    asyncio.run(run_registrations())


if __name__ == "__main__":
    main()