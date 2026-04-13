"""Debug: 获取生日页面的真实 HTML 结构"""
import asyncio, random, string
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"], slow_mo=80)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await context.new_page()

        await page.goto("https://signup.live.com/signup", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # 同意弹窗
        for sel in ['button:has-text("同意并继续")', 'a:has-text("同意并继续")']:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    break
            except: pass
        await page.wait_for_timeout(1500)

        # 填邮箱 (更宽泛的选择器)
        adj = random.choice(["swift","bright","cool"])
        noun = random.choice(["user","hub","link"])
        n = "".join(random.choices(string.digits, k=4))
        email = f"{adj}{noun}{n}@outlook.com"
        password = "TestPass123!"

        for email_sel in ["#MemberName", 'input[name="loginfmt"]', 'input[type="email"]', 'input']:
            try:
                el = page.locator(email_sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.fill(email)
                    break
            except: pass
        await page.wait_for_timeout(500)
        for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(); break
            except: pass
        await page.wait_for_timeout(3000)

        # 填密码
        for sel in ['input[name="passwd"]', 'input[type="password"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.fill(password); break
            except: pass
        await page.wait_for_timeout(500)
        for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(); break
            except: pass
        await page.wait_for_timeout(4000)

        # 等待年份页面
        for year_sel in ['input[aria-label*="年"]', 'input[placeholder*="年"]', '#BirthYear',
                         'input[placeholder="年份"]', 'input']:
            try:
                await page.wait_for_selector(year_sel, timeout=6000)
                break
            except: pass

        # 抓取页面 HTML 和所有 input/select/button 信息
        html_snippet = await page.inner_html("form") if await page.locator("form").count() > 0 else await page.inner_html("body")
        
        # 专门抓下拉框信息
        dropdown_info = await page.evaluate("""
            () => {
                const result = {};
                // select elements
                const selects = document.querySelectorAll('select');
                result.selects = Array.from(selects).map((s, i) => ({
                    index: i,
                    id: s.id,
                    name: s.name,
                    value: s.value,
                    options: Array.from(s.options).slice(0,5).map(o => ({value: o.value, text: o.text}))
                }));
                // input elements
                const inputs = document.querySelectorAll('input');
                result.inputs = Array.from(inputs).map((inp, i) => ({
                    index: i,
                    id: inp.id,
                    name: inp.name,
                    type: inp.type,
                    placeholder: inp.placeholder,
                    ariaLabel: inp.getAttribute('aria-label'),
                    value: inp.value
                }));
                // buttons
                const buttons = document.querySelectorAll('button, input[type=submit]');
                result.buttons = Array.from(buttons).map(b => ({text: b.innerText || b.value, id: b.id}));
                return result;
            }
        """)

        import json
        print("\n=== DROPDOWN / INPUT INFO ===")
        print(json.dumps(dropdown_info, ensure_ascii=False, indent=2))
        
        # Save page HTML
        with open("debug_birthday_page.html", "w", encoding="utf-8") as f:
            f.write(html_snippet[:50000])
        print("\nHTML saved to debug_birthday_page.html")

        await page.wait_for_timeout(3000)
        await browser.close()

asyncio.run(main())
