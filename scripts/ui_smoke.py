"""Run against a local running server; needs the optional ui-test dependencies."""
import os
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run():
    with sync_playwright() as p:
        binary=os.getenv('BROWSER_BIN') or shutil.which('chromium')
        browser=p.chromium.launch(headless=True, executable_path=binary, args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(os.getenv('APP_URL','http://127.0.0.1:8000'))
        expect(page.locator('#connection')).to_contain_text('Network ready')
        page.locator('[data-example="cheapest"]').click()
        page.locator('#submit').click()
        expect(page.locator('.recommended .cost')).to_contain_text('$2,100.00')
        expect(page.locator('.card')).to_have_count(3)
        page.locator('.recommended summary').click()
        expect(page.locator('.recommended .leg')).to_have_count(2)
        page.locator('[data-example="fastest"]').click()
        page.locator('#submit').click()
        expect(page.locator('.recommended .cost')).to_contain_text('$3,400.00')
        page.locator('[data-example="clarify"]').click()
        page.locator('#submit').click()
        expect(page.locator('.clarification')).to_be_visible()
        page.locator('#message').fill('15 pallets')
        page.locator('#submit').click()
        expect(page.locator('.recommended .cost')).to_contain_text('$2,100.00')
        page.reload()
        expect(page.locator('.recommended .cost')).to_contain_text('$2,100.00')
        output=Path(os.getenv('SCREENSHOT_DIR','/tmp/routemind-ui'))
        output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'desktop.png'),full_page=True)
        page.locator('[data-example="no-route"]').click()
        page.locator('#submit').click()
        expect(page.locator('.no-route')).to_be_visible()
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(output/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
        assert not errors, errors
        browser.close()
        print('Browser checks passed: cheapest, fastest, clarification, reload persistence, no-route, mobile layout; no JS errors.')


if __name__=='__main__': run()
