"""
Auto Email Registration Service
Automatically register Outlook emails and obtain Microsoft OAuth2 credentials
"""

import asyncio
import json
import random
import re
import secrets
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


def generate_random_email() -> str:
    """Generate a random Outlook email address"""
    # Generate random username
    adjectives = ['cool', 'fast', 'smart', 'bright', 'quick', 'sharp', 'swift', 'clever', 'bright', 'keen']
    nouns = ['user', 'account', 'mail', 'box', 'hub', 'spot', 'zone', 'link', 'node', 'gate']
    numbers = ''.join(random.choices(string.digits, k=4))

    username = f"{random.choice(adjectives)}{random.choice(nouns)}{numbers}"
    return f"{username}@outlook.com"


def generate_random_password() -> str:
    """Generate a strong random password"""
    # Microsoft password requirements: 8+ chars, mix of upper/lower/digits/special
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%^&*"),
    ]

    # Fill remaining length
    remaining_length = random.randint(4, 8)  # Total 8-12 chars
    password.extend(random.choices(chars, k=remaining_length))

    # Shuffle
    random.shuffle(password)
    return ''.join(password)


class AutoEmailRegistrationService:
    """Service for automatically registering Outlook emails and obtaining OAuth2 credentials"""

    def __init__(self):
        self.outlook_signup_url = "https://signup.live.com/signup"
        self.microsoft_token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    async def register_outlook_account(self) -> Optional[Dict]:
        """
        Attempt to automatically register an Outlook account
        Returns account data if successful, None if failed
        """
        email = generate_random_email()
        password = generate_random_password()

        print(f"Attempting to register Outlook account: {email}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # Need visible browser for CAPTCHA solving
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to Outlook signup
                await page.goto(self.outlook_signup_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Try to fill email
                try:
                    # Look for email input field
                    email_selectors = [
                        'input[name="loginfmt"]',
                        'input[type="email"]',
                        'input[placeholder*="email"]',
                        'input[placeholder*="Email"]',
                        '#iSignupAction',
                        '#MemberName'
                    ]

                    email_input = None
                    for selector in email_selectors:
                        try:
                            await page.wait_for_selector(selector, timeout=5000)
                            email_input = page.locator(selector).first
                            if await email_input.count() > 0:
                                break
                        except:
                            continue

                    if not email_input:
                        raise Exception("Could not find email input field")

                    # Type email character by character
                    await email_input.click()
                    for char in email:
                        await email_input.press(char)
                        await page.wait_for_timeout(random.randint(100, 200))

                    # Try to proceed
                    next_buttons = [
                        'input[type="submit"]',
                        'button[type="submit"]',
                        'input[value="Next"]',
                        'button:has-text("Next")',
                        '#iSignupAction'
                    ]

                    next_clicked = False
                    for button_sel in next_buttons:
                        try:
                            button = page.locator(button_sel).first
                            if await button.count() > 0 and await button.is_visible():
                                await button.click()
                                next_clicked = True
                                break
                        except:
                            continue

                    if not next_clicked:
                        raise Exception("Could not find Next button")

                    # Wait for response - this is where CAPTCHA usually appears
                    await page.wait_for_timeout(3000)

                    # Check if we got past email step
                    current_url = page.url
                    if "signup" in current_url and ("password" in current_url or "passwd" in await page.content()):
                        print("Email step passed, attempting password...")

                        # Try to fill password
                        password_selectors = [
                            'input[name="passwd"]',
                            'input[type="password"]',
                            'input[placeholder*="password"]',
                            'input[placeholder*="Password"]'
                        ]

                        password_input = None
                        for selector in password_selectors:
                            try:
                                await page.wait_for_selector(selector, timeout=5000)
                                password_input = page.locator(selector).first
                                if await password_input.count() > 0:
                                    break
                            except:
                                continue

                        if password_input:
                            await password_input.click()
                            for char in password:
                                await password_input.press(char)
                                await page.wait_for_timeout(random.randint(100, 200))

                            # Try to submit
                            submit_buttons = [
                                'input[type="submit"]',
                                'button[type="submit"]',
                                'input[value="Create account"]',
                                'button:has-text("Create account")'
                            ]

                            submit_clicked = False
                            for button_sel in submit_buttons:
                                try:
                                    button = page.locator(button_sel).first
                                    if await button.count() > 0 and await button.is_visible():
                                        await button.click()
                                        submit_clicked = True
                                        break
                                except:
                                    continue

                            if submit_clicked:
                                # Wait for account creation
                                await page.wait_for_timeout(5000)

                                # Check if account was created successfully
                                if "outlook.com" in page.url or "login.live.com" in page.url:
                                    print(f"Account creation appears successful for {email}")
                                    return {
                                        "email": email,
                                        "password": password,
                                        "status": "created",
                                        "created_at": datetime.now().isoformat()
                                    }
                                else:
                                    print(f"Account creation may have failed - current URL: {page.url}")
                            else:
                                print("Could not find submit button")
                        else:
                            print("Could not find password field")
                    else:
                        # Check for errors
                        error_text = ""
                        try:
                            error_selectors = [
                                '.error',
                                '.field-validation-error',
                                '[role="alert"]',
                                '.ms-MessageBar-text'
                            ]
                            for selector in error_selectors:
                                elements = page.locator(selector)
                                if await elements.count() > 0:
                                    error_text = await elements.first.inner_text()
                                    break
                        except:
                            pass

                        if error_text:
                            print(f"Email validation failed: {error_text}")
                        else:
                            print("Email step did not proceed - likely CAPTCHA or other blocking")

                except Exception as e:
                    print(f"Registration failed: {str(e)}")

                # If we get here, registration likely failed
                return None

            except Exception as e:
                print(f"Unexpected error during registration: {str(e)}")
                return None

            finally:
                await browser.close()

    def create_azure_ad_app(self, access_token: str) -> Optional[str]:
        """
        Attempt to create Azure AD application (requires Azure subscription)
        This is very difficult to automate and usually requires manual setup
        """
        # This would require Azure AD Graph API or Microsoft Graph API
        # and an Azure subscription with appropriate permissions
        # For now, return None to indicate manual setup required
        print("Azure AD app creation requires manual setup in Azure portal")
        return None

    def perform_oauth_flow(self, client_id: str, email: str, password: str) -> Optional[str]:
        """
        Perform OAuth2 authorization code flow to get refresh token
        This requires browser automation and is complex
        """
        # This is the most complex part and usually requires manual intervention
        # For automated flow, we'd need to:
        # 1. Launch browser to authorization URL
        # 2. Handle login redirects
        # 3. Extract authorization code
        # 4. Exchange for tokens

        print("OAuth2 flow requires manual browser interaction for security")
        return None

    async def create_complete_account(self) -> Optional[Dict]:
        """
        Create a complete account with email, password, refresh_token, and client_id
        This is the main entry point
        """
        print("Starting automated account creation...")

        # Step 1: Register Outlook account
        account_data = await self.register_outlook_account()
        if not account_data:
            print("Failed to register Outlook account automatically")
            return None

        # Step 2: Get Microsoft OAuth2 credentials
        # Note: These steps are extremely difficult to automate due to security measures

        print("Account created but OAuth2 setup requires manual steps:")
        print("1. Create Azure AD app at: https://portal.azure.com")
        print("2. Perform OAuth2 authorization flow")
        print("3. Use the credentials in the format: email|password|refresh_token|client_id")

        # Return partial data - user will need to complete OAuth2 setup manually
        return {
            "email": account_data["email"],
            "password": account_data["password"],
            "microsoft_refresh_token": None,  # Requires manual OAuth2
            "microsoft_client_id": None,      # Requires manual Azure AD setup
            "status": "partial",
            "message": "Email created, OAuth2 credentials require manual setup"
        }


# Test function
async def test_auto_registration():
    """Test the auto registration functionality"""
    service = AutoEmailRegistrationService()

    print("Testing automated Outlook account registration...")
    print("Note: This will likely fail due to CAPTCHA and security measures")
    print("=" * 60)

    # First test: just generate random credentials
    email = generate_random_email()
    password = generate_random_password()
    print(f"Generated credentials: {email} / {password}")

    # Test basic browser launch (without full registration)
    print("\nTesting browser launch...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,  # Use headless for testing
                args=['--disable-blink-features=AutomationControlled']
            )
            page = await browser.new_page()
            await page.goto("https://www.microsoft.com", wait_until="domcontentloaded")
            title = await page.title()
            print(f"Browser test successful - page title: {title}")
            await browser.close()
    except Exception as e:
        print(f"Browser test failed: {e}")

    print("\nConclusion: Automated registration is extremely difficult due to:")
    print("- CAPTCHA on signup forms")
    print("- Azure AD app registration requiring manual portal access")
    print("- OAuth2 authorization requiring user consent")
    print("- Microsoft security measures against automation")
    print("\nRecommendation: Use manual registration process as described in the documentation")


async def test_api_integration():
    """Test the API integration with the server"""
    print("Testing API integration...")

    try:
        # Test basic server connectivity
        import requests
        response = requests.get("http://127.0.0.1:4173/")
        if response.status_code == 200:
            print("✓ Server is running and accessible")
        else:
            print(f"✗ Server responded with status {response.status_code}")
            return

        # Test auto-create endpoint (will fail without auth, but tests the endpoint exists)
        response = requests.post("http://127.0.0.1:4173/api/admin/registration/auto-create",
                               json={}, timeout=10)
        if response.status_code == 401:
            print("✓ Auto-create endpoint exists and requires authentication as expected")
        else:
            print(f"? Auto-create endpoint returned status {response.status_code}")

        print("✓ API integration test completed")

    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to server - make sure server.py is running")
    except Exception as e:
        print(f"✗ API test failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_auto_registration())
    asyncio.run(test_api_integration())