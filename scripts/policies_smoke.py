"""Policy UI smoke test; model-answer displays use fixtures, not paid model calls."""
import json
import os
import shutil
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(os.getenv('APP_URL','http://127.0.0.1:8000'))
    page.get_by_role('link',name='Carrier policies').click()
    page.wait_for_function("document.querySelector('#carrier-one').options.length === 11")
    page.get_by_role('button',name='Compare two carriers',exact=True).click()
    assert page.input_value('#carrier-one')=='C01'
    assert page.input_value('#carrier-two')=='C04'
    with page.expect_response('**/api/v1/policies/questions') as response:
        page.get_by_role('button',name='Find policy information').click()
    data=response.value.json()
    page.locator('#policy-result').wait_for(state='visible')
    assert len(data['evidence'])>0
    assert {'C01','C04'} <= {e['carrier_id'] for e in data['evidence']}
    assert page.locator('#sources details').count()==len(data['evidence'])
    page.locator('#sources summary').first.click()
    assert page.locator('#sources details').first.get_attribute('open') is not None
    # Exercise model-result UI with a validated-source fixture, without external calls.
    source=data['evidence'][0]
    data.update(status='answered',mode='model-assisted-extractive',warnings=[],
                findings=[{'source_id':source['source_id'],'quote':source['text'],'carrier_name':source['carrier_name']}],
                unanswered_questions=['What packaging is required?'])
    page.route('**/api/v1/policies/questions',lambda route:route.fulfill(json=data))
    page.get_by_role('button',name='Find policy information').click()
    page.get_by_role('heading',name='What the documents say',exact=True).wait_for()
    page.get_by_text('What packaging is required?',exact=True).wait_for()
    assert page.locator('#findings blockquote').inner_text()==source['text']
    page.locator('#findings a').click()
    assert page.locator('#sources details').first.get_attribute('open') is not None
    data.update(status='not_documented',findings=[])
    page.get_by_role('button',name='Find policy information').click()
    page.get_by_role('heading',name='Not answered by the retrieved documents',exact=True).wait_for()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path='/tmp/routemind-policies-mobile.png',full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.screenshot(path='/tmp/routemind-policies.png',full_page=True)
    page.unroute('**/api/v1/policies/questions')
    page.route('**/api/v1/policies/questions',lambda route:route.fulfill(status=503,json={'detail':'Unavailable'}))
    page.get_by_role('button',name='Find policy information').click()
    page.locator('#policy-error').wait_for(state='visible')
    assert page.locator('#ask').is_enabled()
    page.locator('a.nav-item[href="/explorer"]').click()
    page.locator('#dataset').wait_for()
    assert not errors, errors
    browser.close()
print('Policy UI: real retrieval/comparison, fixture answers/gaps, citations, errors, navigation and mobile passed.')
