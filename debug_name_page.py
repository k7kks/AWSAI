"""
调试脚本: 检查名字页面的真实DOM结构
目标: 到达密码页后的生日页后到达名字页，打印所有输入框信息
"""
import asyncio
import random
import string
from pathlib import Path

from playwright.async_api import async_playwright

screenshots_dir = Path("run/ui-shots")
screenshots_dir.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await context.new_page()

        # 生成一次性用账号信息
        adj = ["swift", "bright", "bold", "cool", "keen"]
        noun = ["user", "hub", "box", "mail", "link"]
        n = "".join(random.choices(string.digits, k=4))
        email = f"{random.choice(adj)}{random.choice(noun)}{n}@outlook.com"
        pw = [random.choice(string.ascii_uppercase), random.choice(string.ascii_lowercase),
              random.choice(string.digits), "!"]
        pw += random.choices(string.ascii_letters + string.digits, k=6)
        random.shuffle(pw)
        password = "".join(pw)
        birth_year = "1992"
        birth_month = "7"
        birth_day = "15"

        print(f"使用账号: {email} / {password}")

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
                    print("同意弹窗已处理")
                    break
            except Exception:
                pass

        # 填写邮箱
        await page.wait_for_selector("#MemberName", timeout=10000)
        await page.locator("#MemberName").fill(email)
        await page.wait_for_timeout(500)

        # 提交邮箱
        await page.locator('#iSignupAction, input[type="submit"]').first.click()
        await page.wait_for_timeout(3000)
        print(f"邮箱提交后 URL: {page.url}")

        # 填写密码
        for sel in ['input[name="passwd"]', 'input[type="password"]']:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                await page.locator(sel).first.fill(password)
                print("密码已填写")
                break
            except Exception:
                pass

        # 提交密码
        for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass
        await page.wait_for_timeout(4000)
        print(f"密码提交后 URL: {page.url}")
        await page.screenshot(path=str(screenshots_dir / "debug_name_birthday_page.png"))

        # 填写生日
        for year_sel in ['input[aria-label*="年"]', 'input[placeholder*="年"]',
                          'input[name="BirthYear"]', '#BirthYear',
                          'input[placeholder="年份"]']:
            try:
                await page.wait_for_selector(year_sel, timeout=5000)
                el = page.locator(year_sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await el.fill(birth_year)
                    print(f"年份已填写 (id={year_sel})")
                    break
            except Exception:
                pass

        # 月份下拉
        try:
            month_btn = page.locator('#BirthMonthDropdown').first
            if await month_btn.count() > 0:
                await month_btn.click()
                await page.wait_for_timeout(600)
                opts = await page.query_selector_all('li[role="option"], [role="option"]')
                print(f"  月份选项数量: {len(opts)}")
                if len(opts) >= int(birth_month):
                    await opts[int(birth_month) - 1].click()
                    print(f"  月份已选: {birth_month}")
                await page.wait_for_timeout(400)
        except Exception as e:
            print(f"月份出错: {e}")

        # 日期下拉
        try:
            day_btn = page.locator('#BirthDayDropdown').first
            if await day_btn.count() > 0:
                await day_btn.click()
                await page.wait_for_timeout(600)
                opts = await page.query_selector_all('li[role="option"], [role="option"]')
                print(f"  日期选项数量: {len(opts)}")
                if len(opts) >= int(birth_day):
                    await opts[int(birth_day) - 1].click()
                    print(f"  日期已选: {birth_day}")
                await page.wait_for_timeout(400)
        except Exception as e:
            print(f"日期出错: {e}")

        # 提交生日
        for btn_sel in ['button:has-text("下一步")', '#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    print(f"生日已提交 (btn={btn_sel})")
                    break
            except Exception:
                pass
        await page.wait_for_timeout(4000)
        print(f"生日提交后 URL: {page.url}")
        await page.screenshot(path=str(screenshots_dir / "debug_name_after_birthday.png"))

        # ====================================================================
        # 重点调试: 检查名字页面的所有输入框
        # ====================================================================
        print("\n=== 检查名字页面 DOM ===")
        print(f"当前 URL: {page.url}")

        # 获取所有 input 元素信息
        inputs_info = await page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('input'));
            return inputs.map(el => ({
                id: el.id,
                name: el.name,
                type: el.type,
                placeholder: el.placeholder,
                ariaLabel: el.getAttribute('aria-label'),
                className: el.className,
                visible: el.offsetWidth > 0 && el.offsetHeight > 0,
                value: el.value,
            }));
        }
        """)
        print(f"\n找到 {len(inputs_info)} 个 input 元素:")
        for i, inp in enumerate(inputs_info):
            print(f"  [{i}] id={inp['id']!r} name={inp['name']!r} type={inp['type']!r} "
                  f"placeholder={inp['placeholder']!r} aria-label={inp['ariaLabel']!r} "
                  f"visible={inp['visible']} class={inp['className']!r}")

        # 获取页面标题
        heading = await page.evaluate("() => document.querySelector('h1')?.textContent || ''")
        print(f"\n页面标题 (h1): {heading!r}")

        # 也打印整个body文本（截断）
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"\n页面文本 (前500字符):\n{body_text[:500]}")

        # 查找所有可见文本输入框
        visible_inputs = [inp for inp in inputs_info if inp['visible'] and inp['type'] in ('text', '', 'email')]
        print(f"\n可见文本输入框: {len(visible_inputs)} 个")
        for i, inp in enumerate(visible_inputs):
            print(f"  [{i}] id={inp['id']!r} name={inp['name']!r} placeholder={inp['placeholder']!r} aria-label={inp['ariaLabel']!r}")

        await page.screenshot(path=str(screenshots_dir / "debug_name_final.png"))
        print("\n截图已保存到 run/ui-shots/debug_name_*.png")

        await browser.close()


asyncio.run(main())
