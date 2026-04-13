"""
CAPTCHA Solver Integration
Integrate with CAPTCHA solving services for automated registration
"""

import asyncio
import base64
import json
import time
from io import BytesIO
from typing import Optional

import requests
from playwright.async_api import Page


class CaptchaSolver:
    """CAPTCHA solving service integration"""

    def __init__(self, service_name: str = "2captcha", api_key: str = None):
        self.service_name = service_name
        self.api_key = api_key or self._get_api_key()
        self.session = requests.Session()

    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment"""
        import os
        return os.getenv(f"{self.service_name.upper()}_API_KEY")

    async def solve_recaptcha_v2(self, page: Page, site_key: str, url: str) -> Optional[str]:
        """Solve reCAPTCHA v2"""
        if not self.api_key:
            print("❌ No CAPTCHA API key configured")
            return None

        try:
            # Take screenshot of the CAPTCHA area
            captcha_element = page.locator('.recaptcha iframe').first
            if await captcha_element.count() == 0:
                captcha_element = page.locator('[class*="captcha"]').first

            screenshot = await page.screenshot()
            screenshot_b64 = base64.b64encode(screenshot).decode()

            if self.service_name == "2captcha":
                return await self._solve_2captcha(site_key, url, screenshot_b64)
            elif self.service_name == "anticaptcha":
                return await self._solve_anticaptcha(site_key, url, screenshot_b64)
            else:
                print(f"❌ Unsupported CAPTCHA service: {self.service_name}")
                return None

        except Exception as e:
            print(f"❌ CAPTCHA solving failed: {e}")
            return None

    async def _solve_2captcha(self, site_key: str, url: str, screenshot_b64: str) -> Optional[str]:
        """Solve using 2Captcha service"""
        try:
            # Submit CAPTCHA for solving
            submit_url = "http://2captcha.com/in.php"
            data = {
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": url,
                "json": 1
            }

            response = self.session.post(submit_url, data=data)
            result = response.json()

            if result.get("status") != 1:
                print(f"❌ 2Captcha submission failed: {result}")
                return None

            request_id = result["request"]

            # Poll for result
            for _ in range(60):  # Wait up to 60 seconds
                await asyncio.sleep(5)

                check_url = "http://2captcha.com/res.php"
                check_data = {
                    "key": self.api_key,
                    "action": "get",
                    "id": request_id,
                    "json": 1
                }

                check_response = self.session.get(check_url, params=check_data)
                check_result = check_response.json()

                if check_result.get("status") == 1:
                    return check_result["request"]
                elif check_result.get("request") == "CAPCHA_NOT_READY":
                    continue
                else:
                    print(f"❌ 2Captcha solving failed: {check_result}")
                    return None

            print("❌ 2Captcha timeout")
            return None

        except Exception as e:
            print(f"❌ 2Captcha error: {e}")
            return None

    async def _solve_anticaptcha(self, site_key: str, url: str, screenshot_b64: str) -> Optional[str]:
        """Solve using Anti-Captcha service"""
        try:
            # Anti-Captcha API integration
            create_task_url = "https://api.anti-captcha.com/createTask"
            task_data = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": url,
                    "websiteKey": site_key
                }
            }

            response = self.session.post(create_task_url, json=task_data)
            result = response.json()

            if result.get("errorId") != 0:
                print(f"❌ Anti-Captcha submission failed: {result}")
                return None

            task_id = result["taskId"]

            # Poll for result
            for _ in range(60):
                await asyncio.sleep(5)

                check_url = "https://api.anti-captcha.com/getTaskResult"
                check_data = {
                    "clientKey": self.api_key,
                    "taskId": task_id
                }

                check_response = self.session.post(check_url, json=check_data)
                check_result = check_response.json()

                if check_result.get("status") == "ready":
                    return check_result["solution"]["gRecaptchaResponse"]
                elif check_result.get("status") == "processing":
                    continue
                else:
                    print(f"❌ Anti-Captcha solving failed: {check_result}")
                    return None

            print("❌ Anti-Captcha timeout")
            return None

        except Exception as e:
            print(f"❌ Anti-Captcha error: {e}")
            return None

    async def solve_hcaptcha(self, page: Page) -> Optional[str]:
        """Solve hCaptcha"""
        print("🔍 hCaptcha solving not yet implemented")
        return None

    async def solve_image_captcha(self, page: Page, captcha_image_selector: str) -> Optional[str]:
        """Solve image-based CAPTCHA"""
        try:
            # Get CAPTCHA image
            image_element = page.locator(captcha_image_selector).first
            if await image_element.count() == 0:
                return None

            screenshot = await image_element.screenshot()
            image_b64 = base64.b64encode(screenshot).decode()

            # Use OCR or CAPTCHA solving service
            # This is a placeholder - would need actual OCR service
            print("🔍 Image CAPTCHA solving requires OCR service integration")
            return None

        except Exception as e:
            print(f"❌ Image CAPTCHA solving failed: {e}")
            return None


class ProxyManager:
    """Manage proxy rotation for anti-detection"""

    def __init__(self, proxy_list: list = None):
        self.proxies = proxy_list or []
        self.current_index = 0

    def get_next_proxy(self) -> Optional[str]:
        """Get next proxy from list"""
        if not self.proxies:
            return None

        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy

    def add_proxy(self, proxy: str):
        """Add proxy to list"""
        if proxy not in self.proxies:
            self.proxies.append(proxy)

    def load_from_file(self, file_path: str):
        """Load proxies from file"""
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.add_proxy(line)
            print(f"✅ Loaded {len(self.proxies)} proxies from {file_path}")
        except Exception as e:
            print(f"❌ Error loading proxies: {e}")

    def get_proxy_config(self) -> Optional[dict]:
        """Get proxy configuration for Playwright"""
        proxy_url = self.get_next_proxy()
        if proxy_url:
            return {"server": proxy_url}
        return None


def setup_anti_detection(page):
    """Setup anti-detection measures"""
    scripts = [
        # Remove webdriver property
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",

        # Mock plugins
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer'},
                {name: 'Chrome PDF Viewer', description: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                {name: 'Native Client', description: '', filename: 'internal-nacl-plugin'}
            ]
        });
        """,

        # Mock languages
        "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'zh-CN', 'zh']});",

        # Mock permissions
        """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """,

        # Mock screen properties
        """
        Object.defineProperty(screen, 'availHeight', {get: () => screen.height - 40});
        Object.defineProperty(screen, 'availWidth', {get: () => screen.width});
        """,

        # Randomize timing
        """
        const originalGetTime = Date.prototype.getTime;
        Date.prototype.getTime = function() {
            return originalGetTime.call(this) + Math.random() * 10;
        };
        """
    ]

    for script in scripts:
        page.add_init_script(script)


# Configuration
CAPTCHA_SERVICES = {
    "2captcha": {
        "name": "2Captcha",
        "url": "https://2captcha.com",
        "cost": "~$1-2 per 1000 CAPTCHAs"
    },
    "anticaptcha": {
        "name": "Anti-Captcha",
        "url": "https://anti-captcha.com",
        "cost": "~$1-3 per 1000 CAPTCHAs"
    },
    "capsolver": {
        "name": "CapSolver",
        "url": "https://capsolver.com",
        "cost": "~$0.5-1 per 1000 CAPTCHAs"
    }
}


def get_captcha_service_info():
    """Get information about available CAPTCHA services"""
    print("Available CAPTCHA solving services:")
    for key, info in CAPTCHA_SERVICES.items():
        print(f"  {key}: {info['name']} - {info['cost']}")
        print(f"    URL: {info['url']}")
        print(f"    Setup: Set {key.upper()}_API_KEY environment variable")
        print()


if __name__ == "__main__":
    get_captcha_service_info()