"""Browser check against a running app: APP_URL=http://127.0.0.1:8001 ..."""
import os
import shutil
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(os.getenv('APP_URL', 'http://127.0.0.1:8000'))
    page.get_by_role('link', name='Data explorer').click()
    page.wait_for_function("document.querySelector('#status').textContent === '18 matching records'")
    page.select_option('#dataset', 'schedules')
    page.wait_for_function("document.querySelector('#page').textContent.startsWith('1–20 of')")
    page.get_by_role('button', name='Next').click()
    page.wait_for_function("document.querySelector('#page').textContent.startsWith('21–40 of')")
    page.fill('#search', 'does-not-exist-xyz')
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_text('No records match your search.', exact=True).wait_for()
    assert page.locator('#next').is_disabled()
    page.fill('#search', '')
    page.select_option('#dataset', 'vectors')
    page.wait_for_function("document.querySelector('#rows').children.length === 20")
    page.locator('#rows button').first.click()
    page.wait_for_function("document.querySelector('#vector-info').textContent.includes('384 dimensions')")
    page.get_by_text('Full stored embedding', exact=True).click()
    assert len(page.locator('#embedding').inner_text()) > 1000
    page.get_by_role('button', name='Close', exact=True).click()
    assert page.locator('#detail').is_hidden()
    page.set_viewport_size({'width':390, 'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path='/tmp/routemind-explorer-mobile.png', full_page=True)
    page.set_viewport_size({'width':1440, 'height':1000})
    page.screenshot(path='/tmp/routemind-explorer.png', full_page=True)
    page.get_by_role('link', name='Shipment planner').click()
    page.locator('#planner').wait_for()
    assert not errors, errors
    browser.close()
print('Explorer navigation, search, paging, stored embeddings, mobile layout: passed')
