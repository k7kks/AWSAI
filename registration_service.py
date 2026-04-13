"""
Registration Service - Full automated AWS Builder ID registration
"""

import asyncio
import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from cryptography.fernet import Fernet


def format_exception_message(error: BaseException) -> str:
    details = str(error).strip()
    if details:
        return f"{type(error).__name__}: {details}"
    return type(error).__name__


async def page_summary(page) -> str:
    try:
        body_text = await page.locator("body").inner_text()
        snippet = " ".join(body_text.split())[:240]
    except Exception:
        snippet = ""
    summary = f"url={page.url}"
    if snippet:
        summary += f", body={snippet}"
    return summary


async def human_type(page, selector: str, text: str) -> None:
    """Type text character by character with random delays to mimic human input."""
    element = page.locator(selector)
    await element.click()
    for ch in text:
        await element.press(ch)
        await page.wait_for_timeout(random.randint(50, 120))


async def human_delay(page, lo: int = 300, hi: int = 800) -> None:
    """Random delay to mimic human pauses."""
    await page.wait_for_timeout(random.randint(lo, hi))


async def random_mouse_move(page) -> None:
    """Move mouse to a random viewport position."""
    x = random.randint(100, 800)
    y = random.randint(100, 500)
    await page.mouse.move(x, y, steps=random.randint(3, 8))


async def check_and_retry_on_error(page, button_selector: str, description: str, max_retries: int = 3) -> bool:
    """Detect AWS error banners and click retry. Returns True if an error was found and retried."""
    error_texts = [
        '抱歉，处理您的请求时出错',
        'Sorry, there was an error processing your request',
        'An error occurred',
    ]
    for attempt in range(max_retries):
        await page.wait_for_timeout(1500)
        body_text = ""
        try:
            body_text = await page.locator("body").inner_text()
        except Exception:
            pass
        found = any(e.lower() in body_text.lower() for e in error_texts)
        if not found:
            return False
        print(f"[retry {attempt+1}/{max_retries}] AWS error detected during {description}, retrying…")
        try:
            btn = page.locator(button_selector).first
            if await btn.count() > 0:
                await btn.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass
    return True


class RegistrationService:
    """Complete AWS Builder ID registration service"""

    def __init__(self, base_dir: Path, encryption_key: bytes, proxy_url: str | None = None):
        self.base_dir = base_dir
        self.configs_dir = base_dir / "configs" / "kiro"
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(encryption_key)
        self.proxy_url = proxy_url  # e.g. "http://host:port"

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
        ]

        # Verification code patterns
        self.code_patterns = [
            r'(?:verification\s*code|验证码|Your code is)[：:\s]*(\d{6})',
            r'^\s*(\d{6})\s*$',
            r'>\s*(\d{6})\s*<',
        ]

    def encrypt_data(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt_data(self, encrypted_data: str) -> str:
        return self.cipher.decrypt(encrypted_data.encode()).decode()

    async def register_account(self, account_data: Dict) -> Dict:
        """
        Register a single AWS Builder ID account

        Args:
            account_data: Account data from database

        Returns:
            Dict containing registration results
        """
        email = account_data['email']
        password = account_data['password']
        refresh_token = self.decrypt_data(account_data['microsoft_refresh_token'])
        client_id = self.decrypt_data(account_data['microsoft_client_id'])

        print(f"Starting registration for {email}")

        try:
            # Step 1: Activate Outlook email
            await self._activate_outlook_email(email, password)

            # Step 2: Register AWS Builder ID
            sso_token = await self._register_aws_builder_id(email, password, refresh_token, client_id)

            # Step 3: Convert SSO token to Kiro credentials
            kiro_creds = await self._convert_sso_to_kiro_credentials(sso_token)

            # Step 4: Save credentials
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            config_dir = self.configs_dir / f"{timestamp}_kiro-auth-token"
            config_dir.mkdir(exist_ok=True)

            config_file = config_dir / "auth.json"
            with open(config_file, 'w') as f:
                json.dump(kiro_creds, f, indent=2)

            return {
                "success": True,
                "email": email,
                "sso_token": sso_token,
                "kiro_credentials": kiro_creds,
                "config_path": str(config_file),
                "aws_builder_id": kiro_creds.get('clientId', ''),
            }

        except Exception as e:
            error_message = format_exception_message(e)
            print(f"Registration failed for {email}: {error_message}")
            return {
                "success": False,
                "email": email,
                "error": error_message,
            }

    async def _activate_outlook_email(self, email: str, password: str) -> None:
        """Activate Outlook email account (headed mode, no proxy)"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to Outlook login
                await page.goto("https://login.live.com/", wait_until="domcontentloaded")
                await human_delay(page, 500, 1200)
                await random_mouse_move(page)

                # Fill email (human-like)
                await page.wait_for_selector('input[name="loginfmt"]', timeout=30000)
                await human_type(page, 'input[name="loginfmt"]', email)
                await human_delay(page)
                await page.locator('input[name="loginfmt"]').press("Enter")

                try:
                    await page.wait_for_selector('input[name="passwd"], #usernameError, [role="alert"]', timeout=30000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "Outlook sign-in did not advance past the email step. "
                        f"{await page_summary(page)}"
                    ) from error

                if await page.locator('input[name="passwd"]').count() == 0:
                    error_text = ""
                    alert_locator = page.locator('#usernameError, [role="alert"]').first
                    if await alert_locator.count() > 0:
                        error_text = " ".join((await alert_locator.inner_text()).split())
                    raise RuntimeError(
                        "Outlook rejected the email step. "
                        f"message={error_text or 'unknown'}; {await page_summary(page)}"
                    )

                # Fill password (human-like)
                try:
                    await page.wait_for_selector('input[name="passwd"]', timeout=30000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "Outlook sign-in did not reach the password step. "
                        "The email may be invalid, blocked, or requires an unsupported challenge. "
                        f"{await page_summary(page)}"
                    ) from error
                await random_mouse_move(page)
                await human_type(page, 'input[name="passwd"]', password)
                await human_delay(page)
                await page.locator('input[name="passwd"]').press("Enter")

                # Handle potential 2FA or security prompts
                await page.wait_for_timeout(3000)

                # Skip "Stay signed in?" prompt if present
                try:
                    stay_btn = page.locator('input[value="No"], button:has-text("No"), #idBtn_Back')
                    if await stay_btn.count() > 0:
                        await stay_btn.first.click()
                        await human_delay(page, 1000, 2000)
                except Exception:
                    pass

                print(f"Outlook activation completed for {email}")

            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "Outlook automation timed out. "
                    f"{await page_summary(page)}"
                ) from error

            finally:
                await browser.close()

    async def _register_aws_builder_id(self, email: str, password: str, refresh_token: str, client_id: str) -> str:
        """Register AWS Builder ID (headed mode, with optional proxy)"""
        async with async_playwright() as p:
            launch_opts: dict = {
                'headless': False,
                'args': ['--disable-blink-features=AutomationControlled'],
            }
            if self.proxy_url:
                launch_opts['proxy'] = {'server': self.proxy_url}

            browser = await p.chromium.launch(**launch_opts)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to AWS Builder ID registration
                await page.goto(
                    "https://signin.aws.amazon.com/signin?client_id=arn:aws:iam::015428540659:user%2Fhomepage&redirect_uri=https%3A%2F%2Fconsole.aws.amazon.com%2Fconsole%2Fhome%3Fstate%3DhashArgs%23%26isauthcode%3Dtrue&response_type=code&state=hashArgs",
                    wait_until="domcontentloaded",
                )
                await human_delay(page, 500, 1000)
                await random_mouse_move(page)

                # Click Create AWS Builder ID
                try:
                    await page.wait_for_selector('text="Create AWS Builder ID"', timeout=15000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "AWS registration page did not show the Builder ID entry point. "
                        f"{await page_summary(page)}"
                    ) from error
                await human_delay(page)
                await page.click('text="Create AWS Builder ID"')

                # Fill email (human-like)
                try:
                    await page.wait_for_selector('input[type="email"]', timeout=30000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "AWS registration did not reach the email entry step. "
                        f"{await page_summary(page)}"
                    ) from error
                await random_mouse_move(page)
                await human_type(page, 'input[type="email"]', email)
                await human_delay(page)
                await page.click('input[type="submit"]')

                # Check for error after email submit
                await check_and_retry_on_error(page, 'input[type="submit"]', 'email submit')

                # Get verification code (poll with retries)
                verification_code = await self._poll_verification_code(refresh_token, client_id)
                if not verification_code:
                    raise RuntimeError("Failed to retrieve verification code from Microsoft Graph")

                # Enter verification code (human-like)
                try:
                    await page.wait_for_selector('input[name="code"]', timeout=30000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "AWS registration did not present the verification code input. "
                        f"{await page_summary(page)}"
                    ) from error
                await random_mouse_move(page)
                await human_type(page, 'input[name="code"]', verification_code)
                await human_delay(page)
                await page.click('input[type="submit"]')

                # Check for error after code submit
                await check_and_retry_on_error(page, 'input[type="submit"]', 'verification code submit')

                # Set password (human-like)
                try:
                    await page.wait_for_selector('input[type="password"]', timeout=30000)
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "AWS registration did not reach the password creation step. "
                        f"{await page_summary(page)}"
                    ) from error
                await random_mouse_move(page)
                await human_type(page, 'input[type="password"]', password)
                await human_delay(page, 200, 500)
                await human_type(page, 'input[name="confirmPassword"]', password)
                await human_delay(page)
                await page.click('input[type="submit"]')

                # Check for error after password submit
                await check_and_retry_on_error(page, 'input[type="submit"]', 'password submit')

                # Wait for completion
                await page.wait_for_timeout(5000)

                # Extract SSO token
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

            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "AWS browser automation timed out. "
                    f"{await page_summary(page)}"
                ) from error

            finally:
                await browser.close()

    async def _poll_verification_code(self, refresh_token: str, client_id: str,
                                        poll_interval: int = 5, max_wait: int = 120) -> Optional[str]:
        """Poll for verification code with retries (every poll_interval seconds, up to max_wait)."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            code = self._get_verification_code(refresh_token, client_id)
            if code:
                return code
            print(f"  Verification code not yet found, retrying in {poll_interval}s…")
            await asyncio.sleep(poll_interval)
        return None

    def _get_verification_code(self, refresh_token: str, client_id: str) -> Optional[str]:
        """Get verification code from email"""
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
                    body = message.get('body', {}).get('content', '')

                    # Search for verification code
                    for pattern in self.code_patterns:
                        match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
                        if match:
                            code = match.group(1)
                            if re.match(r'^\d{6}$', code):
                                return code

        return None

    async def _convert_sso_to_kiro_credentials(self, sso_token: str) -> Dict:
        """Convert AWS SSO token to Kiro credentials"""
        # Register OIDC client
        register_data = {
            'clientName': 'Kiro IDE',
            'clientType': 'public',
            'scopes': [
                'codewhisperer:completions',
                'codewhisperer:analysis',
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
        max_attempts = 60
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
                    await asyncio.sleep(2)
                    continue
                else:
                    raise Exception(f"Token exchange failed: {error}")
            else:
                token_response.raise_for_status()
        else:
            raise Exception("Token polling timed out")

        return {
            'accessToken': token_info['accessToken'],
            'refreshToken': token_info['refreshToken'],
            'clientId': client_data['clientId'],
            'clientSecret': client_data['clientSecret'],
            'expiresAt': (datetime.now() + timedelta(seconds=token_info.get('expiresIn', 3600))).isoformat(),
            'authMethod': 'builder-id',
            'region': 'us-east-1'
        }


# Global service instance
_registration_service = None

def get_registration_service(base_dir: Path, encryption_key: bytes,
                             proxy_url: str | None = None) -> RegistrationService:
    global _registration_service
    if _registration_service is None:
        _registration_service = RegistrationService(base_dir, encryption_key, proxy_url=proxy_url)
    return _registration_service