"""
调试脚本: 检查CAPTCHA页面的iframe和按钮结构
到达验证码页后，打印所有iframe和按钮信息
"""
import asyncio
import random
import string
from pathlib import Path

from playwright.async_api import async_playwright

screenshots_dir = Path("run/ui-shots")
screenshots_dir.mkdir(parents=True, exist_ok=True)

# 用之前成功到达名字步骤的账号凭据（或生成新的）
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=60,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await context.new_page()

        # 生成账号
        mid = "".join(random.choices(string.ascii_lowercase, k=3))
        n = "".join(random.choices(string.digits, k=6))
        email = f"debug{mid}{n}@outlook.com"
        pw = [random.choice(string.ascii_uppercase), random.choice(string.ascii_lowercase),
              random.choice(string.digits), "!"]
        pw += random.choices(string.ascii_letters + string.digits, k=6)
        random.shuffle(pw)
        password = "".join(pw)
        print(f"使用: {email} / {password}")

        # 打开注册页
        await page.goto("https://signup.live.com/signup", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # 同意弹窗
        for sel in ['button:has-text("同意并继续")', 'a:has-text("同意并继续")']:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

        # 邮箱
        await page.wait_for_selector("#MemberName", timeout=10000)
        await page.locator("#MemberName").fill(email)
        await page.wait_for_timeout(500)
        await page.locator('#iSignupAction, input[type="submit"]').first.click()
        await page.wait_for_timeout(3000)

        # 密码
        for sel in ['input[name="passwd"]', 'input[type="password"]']:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                await page.locator(sel).first.fill(password)
                break
            except Exception:
                pass
        for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass
        await page.wait_for_timeout(4000)

        # 生日年份
        for year_sel in ['input[aria-label*="年"]', 'input[placeholder*="年"]', 'input[name="BirthYear"]',
                          '#BirthYear', 'input[placeholder="年份"]']:
            try:
                await page.wait_for_selector(year_sel, timeout=5000)
                el = page.locator(year_sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await el.fill("1992")
                    break
            except Exception:
                pass

        # 月份
        try:
            month_btn = page.locator('#BirthMonthDropdown').first
            if await month_btn.count() > 0:
                await month_btn.click()
                await page.wait_for_timeout(600)
                opts = await page.query_selector_all('li[role="option"], [role="option"]')
                if len(opts) >= 7:
                    await opts[6].click()
                await page.wait_for_timeout(400)
        except Exception as e:
            print(f"月份出错: {e}")

        # 日期
        try:
            day_btn = page.locator('#BirthDayDropdown').first
            if await day_btn.count() > 0:
                await day_btn.click()
                await page.wait_for_timeout(600)
                opts = await page.query_selector_all('li[role="option"], [role="option"]')
                if len(opts) >= 15:
                    await opts[14].click()
                await page.wait_for_timeout(400)
        except Exception as e:
            print(f"日期出错: {e}")

        # 提交生日
        for btn_sel in ['button:has-text("下一步")', '#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass
        await page.wait_for_timeout(4000)

        # 姓名
        await page.wait_for_timeout(2000)
        inputs_all = await page.locator('input[type="text"]:visible, input:not([type="hidden"]):not([type="submit"]):not([type="checkbox"]):visible').all()
        visible = []
        for el in inputs_all:
            try:
                if await el.is_visible():
                    visible.append(el)
            except Exception:
                pass
        if len(visible) >= 2:
            await visible[0].fill("Smith")
            await page.wait_for_timeout(200)
            await visible[1].fill("Alex")
            print("姓名已填写")
        
        for btn_sel in ['button:has-text("下一步")', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass
        await page.wait_for_timeout(5000)
        print(f"姓名提交后 URL: {page.url}")
        await page.screenshot(path=str(screenshots_dir / "debug_captcha_page.png"))

        # ====================================================================
        # 重点调试: 检查CAPTCHA页面
        # ====================================================================
        print(f"\n=== 检查CAPTCHA页面 ===")

        # 检查 iframe
        frames = page.frames
        print(f"\n当前frames数量: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"  Frame[{i}]: url={frame.url!r} name={frame.name!r}")

        # 主frame的按钮
        print("\n主frame按钮:")
        btns = await page.evaluate("""
        () => Array.from(document.querySelectorAll('button, input[type=button], input[type=submit]')).map(el => ({
            tag: el.tagName, id: el.id, type: el.type,
            text: el.textContent?.trim(),
            ariaLabel: el.getAttribute('aria-label'),
            visible: el.offsetWidth > 0 && el.offsetHeight > 0,
            className: el.className,
        }))
        """)
        for btn in btns:
            print(f"  btn: text={btn['text']!r} id={btn['id']!r} aria={btn['ariaLabel']!r} "
                  f"visible={btn['visible']} class={str(btn['className'])[:50]!r}")

        # 每个iframe的按钮
        for i, frame in enumerate(frames[1:], 1):
            if "about:blank" in frame.url:
                continue
            print(f"\nFrame[{i}] 按钮 (url={frame.url[:60]!r}):")
            try:
                btns = await frame.evaluate("""
                () => Array.from(document.querySelectorAll('button, input[type=button]')).map(el => ({
                    tag: el.tagName, id: el.id,
                    text: el.textContent?.trim(),
                    ariaLabel: el.getAttribute('aria-label'),
                    visible: el.offsetWidth > 0 && el.offsetHeight > 0,
                    className: el.className,
                }))
                """)
                for btn in btns:
                    print(f"  btn: text={btn['text']!r} id={btn['id']!r} aria={btn['ariaLabel']!r} "
                          f"visible={btn['visible']} class={str(btn['className'])[:50]!r}")
            except Exception as e:
                print(f"  获取按钮失败: {e}")

        # 页面body文本
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"\n页面文本 (前300字符):\n{body_text[:300]}")

        print("\n截图: run/ui-shots/debug_captcha_page.png")
        print("按 Ctrl+C 退出或等待...")
        await page.wait_for_timeout(8000)
        await browser.close()


asyncio.run(main())
