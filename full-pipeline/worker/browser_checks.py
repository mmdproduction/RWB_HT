"""Trusted browser driver. Model data can select only bounded declarative actions."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from product_contract import endpoint_for, validate_value


def main():
    base=os.environ.get('BASE_URL','http://frontend').rstrip('/')
    output=Path(os.environ.get('RESULTS_DIR','/results'));output.mkdir(parents=True,exist_ok=True)
    plan=json.loads(Path('/checks/product-plan.json').read_text())
    scenarios=json.loads(Path('/checks/browser-acceptance.json').read_text())
    width=int(os.environ.get('VIEWPORT_WIDTH','360'))
    if width not in (360,1280): raise ValueError('Unsupported browser viewport')
    report_path=output/f'browser-report-{width}.json'
    report={'status':'running','scenarios':[],'viewports':[width],
            'limits':'Checks interactions, contract responses, runtime exceptions and overflow; does not certify visual design quality.'}
    target=urlsplit(base)
    primary_actions={a['id']:a['endpointId'] for screen in plan['screens'] for a in screen['actions'] if a['primary'] and a['kind']=='submit'}
    primary_executed=False
    with sync_playwright() as driver:
        browser=driver.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            for index,scenario in enumerate(scenarios,1):
                for width,height in ((width,800 if width==360 else 900),):
                    context=browser.new_context(base_url=base,viewport={'width':width,'height':height},service_workers='block')
                    page=context.new_page();page.set_default_timeout(12000)
                    errors=[];responses=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('response',lambda response:responses.append(response) if '/api/generated/' in response.url else None)
                    item={'name':scenario['name'],'role':scenario['role'],'width':width,'outcome':scenario['outcome'],'status':'running'}
                    report['scenarios'].append(item)
                    screenshot=f'{index:02}-{width}.png'
                    primary_clicks=[]
                    try:
                        login=context.request.post('/api/auth/login',data={'role':scenario['role']})
                        assert login.status==200, 'Browser login failed: '+str(login.status)
                        identity=login.json()
                        page.add_init_script('sessionStorage.setItem("demo-token",'+json.dumps(identity['token'])+');'
                                             'sessionStorage.setItem("demo-role",'+json.dumps(scenario['role'])+');')
                        page.goto('/',wait_until='domcontentloaded')
                        expect(page.locator('generated-panel')).to_be_visible()
                        for step in scenario['steps']:
                            locator=page.get_by_test_id(step['testId'])
                            action=step['action']
                            if action=='fill': locator.fill(step['value'])
                            elif action=='select': locator.select_option(step['value'])
                            elif action=='check': locator.set_checked(step['value'])
                            elif action=='click':
                                if step['testId'] in primary_actions: primary_clicks.append((primary_actions[step['testId']],len(responses)))
                                if step['testId'] in primary_actions and scenario['outcome']!='validation-error':
                                    endpoint_id=primary_actions[step['testId']]
                                    def matches(response):
                                        try: return endpoint_for(plan,response.request.method,urlsplit(response.url).path)['id']==endpoint_id
                                        except ValueError: return False
                                    with page.expect_response(matches): locator.click()
                                else: locator.click()
                            elif action=='expectText': expect(locator).to_contain_text(step['value'])
                            elif action=='expectVisible': expect(locator).to_be_visible()
                            else: raise ValueError('Unsupported browser action')
                        # This JS is fixed trusted measurement, never supplied by the model.
                        overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 2')
                        assert not overflow, f'Frontend horizontal page overflow at {width}px'
                        assert not errors, 'Frontend uncaught JavaScript: '+'; '.join(errors)
                        for response in responses:
                            parsed=urlsplit(response.url)
                            if parsed.netloc!=target.netloc: raise AssertionError('Frontend called an unexpected origin')
                            if response.status==401: continue  # productFetch may renew an expired transport token.
                            endpoint=endpoint_for(plan,response.request.method,parsed.path)
                            expected=next((r for r in endpoint['responses'] if r['status']==response.status),None)
                            assert expected is not None, 'Frontend response status absent from product contract: '+str(response.status)
                            if response.status!=204: validate_value(response.json(),expected['bodySchema'],'browser API response')
                        for endpoint_id,start in primary_clicks:
                            statuses=[]
                            for response in responses[start:]:
                                endpoint=endpoint_for(plan,response.request.method,urlsplit(response.url).path)
                                if endpoint['id']==endpoint_id: statuses.append(response.status)
                            if scenario['outcome']=='success':
                                assert any(200<=status<300 for status in statuses),'Frontend primary action has no successful business request'
                                primary_executed=True;item['primaryBusinessRequestVerified']=True
                            elif scenario['outcome']=='provider-failure':
                                assert any(status in (402,422,503) for status in statuses),'Frontend expected provider failure was not executed'
                                assert not any(200<=status<300 for status in statuses),'Frontend provider failure produced a successful business side effect'
                            else:
                                assert not any(200<=status<300 for status in statuses),'Frontend accepted invalid input as a successful business action'
                        item['status']='passed'
                        print('PASS browser '+scenario['name']+f' [{width}px]',flush=True)
                    except Exception as error:
                        item['status']='failed';item['error']=str(error)[:10000];report['status']='failed'
                        raise AssertionError('Frontend browser acceptance: '+json.dumps(item,ensure_ascii=False)) from error
                    finally:
                        try: page.screenshot(path=str(output/screenshot),full_page=True);item['screenshot']=screenshot
                        except Exception: pass
                        context.close()
                        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        finally:
            browser.close()
    assert primary_executed,'Frontend browser acceptance: primary action never produced a successful contracted business request'
    report['status']='passed'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
