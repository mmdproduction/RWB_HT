"""Trusted runner for declarative model-proposed HTTP acceptance. No Python from the model."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def subset(actual,expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and all(k in actual and subset(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and all(any(subset(a,e) for a in actual) for e in expected)
    return actual==expected


def main():
    base=os.environ.get('BASE_URL','http://frontend').rstrip('/')
    tests=json.loads(Path('/checks/domain-acceptance.json').read_text())
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
        return response.status,payload
    for test in tests:
        status,login=request('POST','/api/auth/login',{'role':test['role']})
        assert status==200,('login',status)
        for index,step in enumerate(test['steps'],1):
            status,body=request(step['method'],step['path'],step.get('body'),login['token'])
            diagnostic={'scenario':test['name'],'step':index,'method':step['method'],'path':step['path'],
                'requestBody':step.get('body'),'expectedStatus':step['status'],'actualStatus':status,
                'expectedContains':step.get('contains',{}),'actualBody':body}
            assert status==step['status'],json.dumps(diagnostic,ensure_ascii=False)
            assert subset(body,step.get('contains',{})),json.dumps(diagnostic,ensure_ascii=False)
        print('PASS '+test['name'],flush=True)


if __name__=='__main__': main()
