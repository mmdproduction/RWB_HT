"""Trusted runner for declarative model-proposed HTTP acceptance. No Python from the model."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import re
from product_contract import endpoint_for, validate_value, resolve_references


def subset(actual,expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and all(k in actual and subset(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and all(any(subset(a,e) for a in actual) for e in expected)
    return actual==expected


def main():
    base=os.environ.get('BASE_URL','http://frontend').rstrip('/')
    tests=json.loads(Path('/checks/domain-acceptance.json').read_text())
    plan_path=Path('/checks/product-plan.json')
    plan=json.loads(plan_path.read_text()) if plan_path.exists() else None
    event_path=Path('/checks/event-contract.json')
    event_ids={e['endpointId'] for e in json.loads(event_path.read_text())['events']} if event_path.exists() else set()
    if event_ids:
        import events_checks
        events_checks.RESULTS.mkdir(exist_ok=True)
        events_checks.RECEIPTS.write_text('')
    def request(method,path,body=None,token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            response=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as error:
            response=error
        raw=response.read()
        try: payload=json.loads(raw) if raw else None
        except ValueError: payload=raw.decode(errors='replace')
        return response.status,payload,response.headers
    for test in tests:
        variables={}
        status,login,_=request('POST','/api/auth/login',{'role':test['role']})
        assert status==200,('login',status)
        for index,step in enumerate(test['steps'],1):
            path=resolve_references(step['path'],variables)
            request_body=resolve_references(step.get('body'),variables)
            expected_body=resolve_references(step.get('contains',{}),variables)
            assert re.fullmatch(r'/api/generated/[A-Za-z0-9_/?=&.%+-]{1,300}',path) and '..' not in path,'Invalid resolved business route'
            if plan and 200<=step['status']<300 and step['method'] in ('POST','PUT'):
                validate_value(request_body,endpoint_for(plan,step['method'],path)['requestSchema'],'actual HTTP request')
            endpoint=endpoint_for(plan,step['method'],path) if plan else None
            tracked=endpoint is not None and endpoint['id'] in event_ids
            before=events_checks.state(login['token']) if tracked and step['status']>=300 else None
            status,body,headers=request(step['method'],path,request_body,login['token'])
            diagnostic={'scenario':test['name'],'step':index,'method':step['method'],'path':path,
                'requestBody':request_body,'expectedStatus':step['status'],'actualStatus':status,
                'expectedContains':expected_body,'actualBody':body}
            assert status==step['status'],json.dumps(diagnostic,ensure_ascii=False)
            if status==204: assert body is None,json.dumps(diagnostic,ensure_ascii=False)
            else: assert subset(body,expected_body),json.dumps(diagnostic,ensure_ascii=False)
            if plan:
                endpoint=endpoint_for(plan,step['method'],path)
                response=next((r for r in endpoint['responses'] if r['status']==status),None)
                assert response is not None,'Response absent from frozen API contract'
                if status!=204: validate_value(body,response['bodySchema'],'actual HTTP response')
            if tracked and 200<=status<300:
                assert headers.get('X-Business-Event-Id'),'Kafka business response missing X-Business-Event-Id: '+path
                events_checks.record(headers['X-Business-Event-Id'],endpoint,status,body,test['role'],login['token'])
            elif tracked:
                assert not headers.get('X-Business-Event-Id') and events_checks.state(login['token'])==before,'Kafka business failure emitted a completion event: '+path
            for name,source in step.get('capture',{}).items():
                captured=body
                for key in source.split('.'): captured=captured[key]
                assert isinstance(captured,(str,int,float,bool)) and captured is not None,'Capture requires scalar business value'
                variables[name]=captured
        print('PASS '+test['name'],flush=True)


if __name__=='__main__': main()
