"""
直接执行 Outlook 邮箱注册 - 真实浏览器操作
"""
import asyncio
import json
import os
import random
import string
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

RESULTS_FILE = Path("registration_results.json")


def gen_email():
    adj = ["swift", "bright", "bold", "cool", "keen", "clear", "smart",
           "live", "real", "pure", "true", "safe", "mild", "calm", "kind",
           "dark", "fast", "high", "warm", "long", "deep", "wide", "near"]
    noun = ["user", "hub", "box", "mail", "link", "spot", "node", "gate",
            "zone", "port", "ring", "base", "nest", "beam", "wave",
            "dock", "lane", "path", "flow", "core", "byte", "peak", "grid"]
    mid = "".join(random.choices(string.ascii_lowercase, k=random.randint(2, 4)))
    n = "".join(random.choices(string.digits, k=6))
    return f"{random.choice(adj)}{mid}{random.choice(noun)}{n}@outlook.com"


def gen_password():
    pw = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%"),
    ]
    pw += random.choices(string.ascii_letters + string.digits, k=6)
    random.shuffle(pw)
    return "".join(pw)


def gen_name():
    first = random.choice(["Alex", "Jordan", "Morgan", "Casey", "Riley",
                           "Drew", "Taylor", "Jamie", "Quinn", "Blake"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones",
                          "Garcia", "Miller", "Davis", "Wilson", "Moore"])
    return first, last


async def _human_type(page, element, text: str) -> None:
    """逐字符打字，带随机延迟，模拟真人输入。"""
    for ch in text:
        await element.press(ch)
        await page.wait_for_timeout(random.randint(60, 160))


def load_results():
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


def save_result(entry):
    results = load_results()
    results.append(entry)
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n💾 已保存到 {RESULTS_FILE}")


async def try_register(index: int):
    email = gen_email()
    password = gen_password()
    first, last = gen_name()
    birth_month = str(random.randint(1, 12))
    birth_day = str(random.randint(1, 28))
    birth_year = str(random.randint(1985, 2000))

    print(f"\n{'='*60}")
    print(f"[账号 {index+1}] 尝试注册: {email}")
    print(f"  密码: {password}")
    print(f"  姓名: {first} {last}  生日: {birth_year}-{birth_month}-{birth_day}")
    print(f"{'='*60}")

    screenshots_dir = Path("run/ui-shots")
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            slow_mo=50,
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": random.choice([1280, 1366, 1440, 1920]),
                       "height": random.choice([768, 800, 900, 1080])},
            locale="en-US",
            timezone_id="America/New_York",
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : originalQuery(parameters);
        """)
        page = await context.new_page()

        step = "start"
        try:
            # ── Step 1: 打开注册页 ──────────────────────────────────────
            await page.goto("https://signup.live.com/signup", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(1500, 2500))
            step = "opened"

            # ── 处理"个人数据导出许可"弹窗 (中国区微软会显示) ────────────
            for agree_sel in [
                'button:has-text("同意并继续")',
                'a:has-text("同意并继续")',
                'input[value="同意并继续"]',
            ]:
                try:
                    btn = page.locator(agree_sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        print("  ✓ 已点击同意并继续")
                        await page.wait_for_timeout(random.randint(1500, 2500))
                        break
                except Exception:
                    pass

            await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_step1.png"))

            # ── Step 2: 输入邮箱 ────────────────────────────────────────
            selectors_email = ["#MemberName", 'input[name="loginfmt"]', 'input[type="email"]']
            email_input = None
            for sel in selectors_email:
                try:
                    await page.wait_for_selector(sel, timeout=5000)
                    email_input = page.locator(sel).first
                    if await email_input.count() > 0:
                        break
                except Exception:
                    pass

            if not email_input:
                raise RuntimeError("找不到邮箱输入框")

            # ── Step 2b: 填邮箱，检测「不可用」错误并重试 ─────────────
            email_ok = False
            for email_attempt in range(6):
                await email_input.click()
                await page.keyboard.press("Control+a")
                await page.wait_for_timeout(random.randint(200, 400))
                await _human_type(page, email_input, email)
                await page.wait_for_timeout(random.randint(600, 1200))

                # 点击下一步
                for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            break
                    except Exception:
                        pass

                await page.wait_for_timeout(random.randint(2000, 3500))

                # 检测邮箱被占用的错误提示
                page_text_check = await page.inner_text("body")
                email_unavailable = any(kw in page_text_check for kw in [
                    "不可用", "unavailable", "isn't available", "is not available",
                    "not available", "already taken", "already exists",
                    "already in use", "该电子邮件地址", "此用户名不可用",
                ])
                if email_unavailable:
                    email = gen_email()
                    print(f"  ⚠ 邮箱已被占用，重试 [{email_attempt+1}/5]: {email}")
                    # 页面仍在邮箱步骤，重新找输入框
                    for sel in ["#MemberName", 'input[name="loginfmt"]', 'input[type="email"]']:
                        try:
                            el = page.locator(sel).first
                            if await el.count() > 0 and await el.is_visible():
                                email_input = el
                                break
                        except Exception:
                            pass
                else:
                    email_ok = True
                    break

            await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_step2.png"))
            step = "after_email_submit"
            print(f"  ✓ 邮箱已填写: {email}")
            print(f"  ✓ 提交邮箱后 URL: {page.url}")

            # ── Step 4: 输入密码 ────────────────────────────────────────
            pwd_input = None
            for sel in ['input[name="passwd"]', 'input[type="password"]']:
                try:
                    await page.wait_for_selector(sel, timeout=8000)
                    pwd_input = page.locator(sel).first
                    if await pwd_input.count() > 0:
                        break
                except Exception:
                    pass

            if pwd_input:
                await pwd_input.click()
                await page.wait_for_timeout(random.randint(300, 600))
                await _human_type(page, pwd_input, password)
                await page.wait_for_timeout(random.randint(700, 1200))
                step = "password_filled"
                print("  ✓ 密码已填写")

                for btn_sel in ['#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            break
                    except Exception:
                        pass

                await page.wait_for_timeout(random.randint(2500, 4000))
                await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_step3.png"))
                step = "after_password"
                print(f"  URL: {page.url}")
            else:
                print("  ⚠ 未找到密码框 —— 可能已显示验证码/阻断页")
                await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_blocked.png"))

            # ── Step 5: 填写姓名（某些流程有，没有就跳过） ────────────────
            first_input = page.locator('#FirstName').first
            last_input  = page.locator('#LastName').first
            if await first_input.count() > 0 and await first_input.is_visible():
                await first_input.click()
                await _human_type(page, first_input, first)
                await page.wait_for_timeout(random.randint(300, 700))
                await last_input.click()
                await _human_type(page, last_input, last)
                await page.wait_for_timeout(random.randint(400, 800))
                for btn_sel in ['button:has-text("下一步")', '#iSignupAction', 'input[type="submit"]', 'button[type="submit"]']:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            break
                    except Exception:
                        pass
                await page.wait_for_timeout(random.randint(2000, 3500))
                step = "after_name"
                print(f"  ✓ 姓名已填写  URL: {page.url}")

            # ── Step 6: 填写国家/生日 ────────────────────────────────────
            try:
                # 等待年份输入框出现（新旧UI均兼容：BirthYear name / aria-label）
                year_appeared = False
                for year_sel in [
                    'input[name="BirthYear"]', '#BirthYear',
                    'input[aria-label*="year" i]', 'input[aria-label*="年"]',
                    'input[placeholder*="年"]',
                ]:
                    try:
                        await page.wait_for_selector(year_sel, timeout=5000)
                        year_el = page.locator(year_sel).first
                        if await year_el.count() > 0 and await year_el.is_visible():
                            await year_el.click()
                            await page.keyboard.press("Control+a")
                            await _human_type(page, year_el, birth_year)
                            # 离开年份输入框，避免它持续占焦点阻塞月份按钮
                            await page.keyboard.press("Tab")
                            await page.wait_for_timeout(random.randint(400, 800))
                            year_appeared = True
                            break
                    except Exception:
                        pass

                if year_appeared:
                    await page.wait_for_timeout(random.randint(300, 600))

                    # ── 国家选择 ──────────────────────────────────────────
                    try:
                        country_sel = page.locator(
                            'select[name="Country"], select[aria-label*="Country" i], '
                            'select[aria-label*="国"], [data-testid="country-dropdown"]'
                        ).first
                        if await country_sel.count() > 0:
                            await country_sel.select_option(value="US")
                            await page.wait_for_timeout(random.randint(400, 700))
                            print("  ✓ 国家已选择: US")
                        else:
                            country_btn = page.locator(
                                '#CountryCode, [aria-label*="Country" i], [aria-label*="国家"]'
                            ).first
                            if await country_btn.count() > 0 and await country_btn.is_visible():
                                await country_btn.click(timeout=4000)
                                await page.wait_for_timeout(600)
                                for us_text in ["United States", "美国"]:
                                    us_opt = page.locator(
                                        f'[role="option"]:has-text("{us_text}"), li:has-text("{us_text}")'
                                    ).first
                                    if await us_opt.count() > 0:
                                        await us_opt.click(timeout=3000)
                                        print(f"  ✓ 国家已选择: {us_text}")
                                        break
                                await page.wait_for_timeout(random.randint(400, 700))
                    except Exception as e:
                        print(f"  ⚠ 国家选择跳过: {e}")

                    # ── 月份/日期选择辅助函数 ──────────────────────────────
                    async def _pick_date_field(selectors: list, value_int: int, label: str):
                        """
                        先尝试 native <select> select_option，
                        再尝试自定义 button 下拉 + role=option 点击（短 timeout），
                        最后回退键盘上下箭头。
                        """
                        # 方案A: native select
                        for sel in selectors:
                            try:
                                el = page.locator(sel).first
                                tag = await el.evaluate("e => e.tagName.toLowerCase()") if await el.count() > 0 else ""
                                if tag == "select":
                                    await el.select_option(index=value_int - 1)
                                    await page.wait_for_timeout(300)
                                    print(f"  ✓ {label} 已选择 (native select index={value_int-1})")
                                    return True
                            except Exception:
                                pass

                        # 方案B: 自定义 button 下拉
                        for sel in selectors:
                            try:
                                btn = page.locator(sel).first
                                if await btn.count() == 0:
                                    continue
                                # 先滚动到可见区域，再用 force=True 强制点击（绕过遮挡检测）
                                try:
                                    await btn.scroll_into_view_if_needed(timeout=3000)
                                except Exception:
                                    pass
                                # 尝试普通点击
                                clicked = False
                                for click_kwargs in [
                                    {"timeout": 3000},
                                    {"force": True, "timeout": 3000},
                                ]:
                                    try:
                                        await btn.click(**click_kwargs)
                                        clicked = True
                                        break
                                    except Exception:
                                        pass
                                if not clicked:
                                    # JS 直接触发 click 事件
                                    el_handle = await btn.element_handle(timeout=2000)
                                    if el_handle:
                                        await page.evaluate("el => el.click()", el_handle)
                                        clicked = True
                                if not clicked:
                                    continue
                                await page.wait_for_timeout(600)
                                # 等待 listbox 或 role=option 出现
                                try:
                                    await page.wait_for_selector(
                                        '[role="listbox"], [role="option"]', timeout=3000
                                    )
                                except Exception:
                                    pass
                                # 先尝试 role=listbox > role=option
                                opts = page.locator('[role="listbox"] [role="option"]')
                                cnt = await opts.count()
                                if cnt == 0:
                                    opts = page.locator('[role="option"]')
                                    cnt = await opts.count()
                                if cnt > 0:
                                    idx = min(value_int - 1, cnt - 1)
                                    await opts.nth(idx).click(timeout=3000)
                                    await page.wait_for_timeout(300)
                                    print(f"  ✓ {label} 已选择 (option index={idx})")
                                    return True
                                # 下拉已打开但找不到 option → 键盘
                                await page.keyboard.press("Home")
                                for _ in range(value_int - 1):
                                    await page.keyboard.press("ArrowDown")
                                    await page.wait_for_timeout(60)
                                await page.keyboard.press("Enter")
                                await page.wait_for_timeout(300)
                                print(f"  ✓ {label} 已选择 (键盘导航 n={value_int})")
                                return True
                            except Exception as e:
                                print(f"  ⚠ {label} 尝试 {sel!r} 失败: {e}")
                                continue
                        print(f"  ⚠ {label} 所有方案均失败")
                        return False

                    # 调试: 输出月份下拉框的HTML结构
                    try:
                        month_info = await page.evaluate("""
                        () => {
                            const btn = document.querySelector('#BirthMonthDropdown');
                            if (!btn) return 'NOT FOUND';
                            const r = btn.getBoundingClientRect();
                            return JSON.stringify({
                                tag: btn.tagName, id: btn.id, type: btn.type,
                                disabled: btn.disabled, hidden: btn.hidden,
                                display: getComputedStyle(btn).display,
                                visibility: getComputedStyle(btn).visibility,
                                rect: {x: Math.round(r.x), y: Math.round(r.y),
                                       w: Math.round(r.width), h: Math.round(r.height)},
                                parentClass: btn.parentElement?.className?.substring(0,60)
                            });
                        }
                        """)
                        print(f"  DEBUG Month btn: {month_info}")
                    except Exception as de:
                        print(f"  DEBUG err: {de}")

                    # 月份
                    await _pick_date_field(
                        ['select[name="BirthMonth"]', '#BirthMonthDropdown',
                         'button[aria-label*="month" i]', 'button[aria-label*="月"]'],
                        int(birth_month), "月份"
                    )
                    await page.wait_for_timeout(random.randint(300, 600))

                    # 日期
                    await _pick_date_field(
                        ['select[name="BirthDay"]', '#BirthDayDropdown',
                         'button[aria-label*="day" i]', 'button[aria-label*="日"]'],
                        int(birth_day), "日期"
                    )
                    await page.wait_for_timeout(500)

                    # 点击"下一步 / Next"
                    for btn_sel in [
                        'button:has-text("Next")', 'button:has-text("下一步")',
                        '#iSignupAction', 'input[type="submit"]', 'button[type="submit"]',
                    ]:
                        try:
                            btn = page.locator(btn_sel).first
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click(timeout=5000)
                                break
                        except Exception:
                            pass
                    await page.wait_for_timeout(random.randint(3000, 5000))
                    step = "after_birthday"
                    print(f"  ✓ 生日已填写  URL: {page.url}")
                    await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_after_birthday.png"))

                    # ── Step 7: 填写姓名 (生日后出现) ─────────────────────
                    try:
                        await page.wait_for_timeout(2000)
                        last_name_filled = False
                        first_name_filled = False

                        # 方法1: get_by_placeholder / get_by_label
                        for last_hint in ["姓氏", "Last name", "Surname"]:
                            try:
                                el = page.get_by_placeholder(last_hint)
                                if await el.count() > 0 and await el.first.is_visible():
                                    await el.first.click()
                                    await _human_type(page, el.first, last)
                                    last_name_filled = True
                                    break
                            except Exception:
                                pass
                        if not last_name_filled:
                            for last_hint in ["姓氏", "Last name"]:
                                try:
                                    el = page.get_by_label(last_hint)
                                    if await el.count() > 0 and await el.first.is_visible():
                                        await el.first.click()
                                        await _human_type(page, el.first, last)
                                        last_name_filled = True
                                        break
                                except Exception:
                                    pass

                        await page.wait_for_timeout(random.randint(300, 600))

                        for first_hint in ["名字", "First name", "Given name"]:
                            try:
                                el = page.get_by_placeholder(first_hint)
                                if await el.count() > 0 and await el.first.is_visible():
                                    await el.first.click()
                                    await _human_type(page, el.first, first)
                                    first_name_filled = True
                                    break
                            except Exception:
                                pass
                        if not first_name_filled:
                            for first_hint in ["名字", "First name"]:
                                try:
                                    el = page.get_by_label(first_hint)
                                    if await el.count() > 0 and await el.first.is_visible():
                                        await el.first.click()
                                        await _human_type(page, el.first, first)
                                        first_name_filled = True
                                        break
                                except Exception:
                                    pass

                        # 方法2: 按位置填写所有可见文本输入框
                        if not (last_name_filled and first_name_filled):
                            all_inputs = await page.locator(
                                'input[type="text"]:visible, input:not([type="hidden"]):not([type="submit"]):not([type="checkbox"]):visible'
                            ).all()
                            visible = []
                            for el in all_inputs:
                                try:
                                    if await el.is_visible():
                                        visible.append(el)
                                except Exception:
                                    pass
                            inputs_info = await page.evaluate("""
                            () => Array.from(document.querySelectorAll('input')).map(el => ({
                                id: el.id, name: el.name, type: el.type,
                                placeholder: el.placeholder,
                                ariaLabel: el.getAttribute('aria-label'),
                                visible: el.offsetWidth > 0 && el.offsetHeight > 0
                            }))
                            """)
                            print(f"  DEBUG 页面输入框: {[x for x in inputs_info if x['visible']]}")
                            if len(visible) >= 2:
                                await visible[0].click()
                                await _human_type(page, visible[0], last)
                                await page.wait_for_timeout(random.randint(300, 600))
                                await visible[1].click()
                                await _human_type(page, visible[1], first)
                                last_name_filled = True
                                first_name_filled = True

                        if last_name_filled and first_name_filled:
                            await page.wait_for_timeout(500)
                            for btn_sel in ['button:has-text("下一步")', 'input[type="submit"]',
                                            'button[type="submit"]']:
                                try:
                                    btn = page.locator(btn_sel).first
                                    if await btn.count() > 0 and await btn.is_visible():
                                        await btn.click()
                                        break
                                except Exception:
                                    pass
                            await page.wait_for_timeout(random.randint(3000, 5000))
                            step = "after_name"
                            print(f"  ✓ 姓名已填写  URL: {page.url}")
                            await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_after_name.png"))

                            # ── Step 8: 处理"长按按钮" CAPTCHA ────────────
                            # CAPTCHA可能在Shadow DOM里
                            try:
                                captcha_handled = False

                                # 方法1: text/role locator (能穿透 Shadow DOM)
                                for sel in [
                                    'text=按住',
                                    'button:text("按住")',
                                    '[aria-label*="按住"]',
                                    'text=Hold',
                                    '[role="button"]:has-text("按住")',
                                    '[role="button"]:has-text("Hold")',
                                ]:
                                    try:
                                        el = page.locator(sel).first
                                        cnt = await el.count()
                                        if cnt > 0:
                                            bbox = await el.bounding_box()
                                            # 如果找到的是文字节点（高度 < 40px），尝试找父级可点击元素
                                            if bbox and bbox["height"] < 40:
                                                parent = page.locator(sel).locator('xpath=ancestor::*[@role="button" or @role="presentation" or self::button][1]').first
                                                if await parent.count() > 0:
                                                    pbbox = await parent.bounding_box()
                                                    if pbbox and pbbox["height"] >= 30:
                                                        el = parent
                                                        bbox = pbbox
                                            print(f"  找到CAPTCHA元素! sel={sel!r} cnt={cnt}")
                                            print(f"  bbox={bbox}")
                                            if bbox and bbox["width"] > 20 and bbox["height"] > 10:
                                                cx = bbox["x"] + bbox["width"] / 2
                                                cy = bbox["y"] + bbox["height"] / 2
                                                await page.mouse.move(cx, cy)
                                                await page.mouse.down()
                                                await page.wait_for_timeout(6000)
                                                await page.mouse.up()
                                                await page.wait_for_timeout(3000)
                                                captcha_handled = True
                                                step = "after_captcha"
                                                print(f"  ✓ 长按完成  URL: {page.url}")
                                                try:
                                                    await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_after_captcha.png"), timeout=5000)
                                                except Exception:
                                                    pass
                                                break
                                    except Exception:
                                        pass

                                # 方法2: 直接用截图坐标（按钮视觉上在约x=705, y=550）
                                if not captcha_handled:
                                    # 检查页面是否有CAPTCHA内容
                                    page_text_cap = await page.inner_text("body")
                                    if "证明你不是机器人" in page_text_cap or "长按" in page_text_cap:
                                        print("  检测到CAPTCHA，尝试视觉坐标长按 (705, 550)...")
                                        await page.mouse.move(705, 550)
                                        await page.mouse.down()
                                        await page.wait_for_timeout(6000)
                                        await page.mouse.up()
                                        await page.wait_for_timeout(3000)
                                        captcha_handled = True
                                        step = "after_captcha"
                                        print(f"  ✓ 尝试长按完成  URL: {page.url}")
                                        try:
                                            await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_after_captcha.png"), timeout=5000)
                                        except Exception:
                                            pass
                            except Exception as e:
                                print(f"  ⚠ CAPTCHA处理出错: {e}")
                        else:
                            print("  ⚠ 姓名页未检测到输入框")
                            await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_name_debug.png"))
                    except Exception as e:
                        print(f"  ⚠ 姓名填写出错: {e}")
                else:
                    print("  ⚠ 未找到年份输入框")
            except Exception as e:
                print(f"  ⚠ 生日填写出错: {e}")

            try:
                await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_final.png"), timeout=5000)
            except Exception:
                pass

            # ── 判断是否成功 ────────────────────────────────────────────
            final_url = page.url
            page_text = await page.inner_text("body")

            captcha_hit = any(
                w in page_text
                for w in ["captcha", "verify you're a human", "prove", "puzzle",
                          "verification", "请完成", "验证", "人机验证",
                          "证明你不是机器人", "长按", "按住"]
            )
            phone_required = any(
                w in page_text.lower()
                for w in ["phone", "手机", "mobile", "sms", "text message"]
            )
            success = (
                "outlook.com" in final_url
                or "login.live.com" in final_url
                or "account successfully" in page_text.lower()
                or "welcome" in page_text.lower()
            )

            status = "unknown"
            note = ""
            if success:
                status = "registered"
                note = "✅ 注册成功！"
            elif phone_required:
                status = "phone_required"
                note = "📱 需要手机验证码 — 无法全自动绕过"
            elif captcha_hit:
                status = "blocked_captcha"
                note = "🔒 遇到验证码 — 需要人工解码服务"
            else:
                status = f"stopped_at_{step}"
                note = f"⚠ 在步骤 [{step}] 停止，请查看截图"

            print(f"\n  结果: {note}")
            result = {
                "index": index + 1,
                "email": email,
                "password": password,
                "name": f"{first} {last}",
                "status": status,
                "note": note,
                "final_url": final_url,
                "step_reached": step,
                "timestamp": datetime.now().isoformat(),
                "screenshots": [str(p) for p in sorted(screenshots_dir.glob(f"reg{index+1}_*.png"))],
            }
            save_result(result)
            return result

        except Exception as exc:
            print(f"  ❌ 异常: {exc}")
            try:
                await page.screenshot(path=str(screenshots_dir / f"reg{index+1}_error.png"), timeout=5000)
            except Exception:
                pass
            return {"email": email, "status": "error", "error": str(exc), "step": step}
        finally:
            await page.wait_for_timeout(1500)
            await browser.close()


async def main():
    total = 3
    print(f"🚀 开始尝试注册 {total} 个 Outlook 邮箱账号")
    print("⚠  注意: 同一 IP 连续注册多个账号本身就会触发风控。")
    print("   建议每个账号间隔 60-120 秒，或使用不同出口 IP。")
    results = []
    for i in range(total):
        r = await try_register(i)
        results.append(r)
        if i < total - 1:
            wait_sec = random.randint(60, 120)
            print(f"\n⏳ 等待 {wait_sec} 秒后再注册下一个账号（降低风控概率）...")
            await asyncio.sleep(wait_sec)

    print("\n\n" + "="*60)
    print("注册结果汇总:")
    for r in results:
        print(f"  [{r.get('index','?')}] {r.get('email','?')} → {r.get('status')} {r.get('note','')}")
    print("="*60)
    print(f"\n截图保存在: run/ui-shots/  结果保存在: {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
