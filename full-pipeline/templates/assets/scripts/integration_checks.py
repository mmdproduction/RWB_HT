"""Trusted HTTP contract/usage/persistence checks for every declared mock provider."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def main():
    spec=json.loads(Path('/checks/app-spec.json').read_text())
    providers=spec.get('externalIntegrations',[])
    base=os.environ.get('BASE_URL','http://frontend').rstrip('/')
    def request(method,path,body=None,token=None,status=200):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try: response=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as error: response=error
        raw=response.read()
        assert response.status==status,(method,path,response.status,status,raw[:2000])
        return json.loads(raw) if raw else None
    token=request('POST','/api/auth/login',{'role':'admin'})['token']
    registry=request('GET','/api/integrations',token=token)
    assert registry=={'mode':'mock','providers':providers},'Mock registry differs from frozen specification'
    if os.environ.get('BUSINESS_USAGE_ONLY')=='1':
        usage=request('GET','/api/integrations/usage',token=token)
        for provider in providers:
            counts=usage.get(provider['id'],{})
            assert counts.get('success',0)>0 and counts.get('failure',0)>0,('Business scenario must invoke successful and failed mock provider calls',provider['id'],counts)
        print('PASS mock integration business usage',flush=True)
        return
    persistence=os.environ.get('PERSISTENCE_ONLY')=='1'
    for provider in providers:
        for operation in provider['operations']:
            path='/api/integrations/'+provider['id']+'/'+operation['id']
            request_id='contract-check-'+provider['id']+'-'+operation['id']
            # ID length is bounded independently of provider/operation label lengths.
            import hashlib
            request_id='contract-'+hashlib.sha256(request_id.encode()).hexdigest()[:32]
            body={'requestId':request_id,'input':operation['inputExample'],'scenario':'success'}
            receipt_path='/api/integrations/calls/'+provider['id']+'/'+operation['id']+'/'+request_id
            if persistence:
                saved=request('GET',receipt_path,token=token)
                replay=request('POST',path,body,token)
                assert saved==replay,('Mock receipt changed after restart',provider['id'],operation['id'])
                continue
            receipt=request('POST',path,body,token)
            expected=dict(operation['response'])
            if provider['kind']=='payment':
                expected.update(amount=body['input']['amount'],currency=body['input']['currency'])
            assert receipt['mode']=='mock' and receipt['success'] is True and receipt['data']==expected,receipt
            assert receipt['providerId']==provider['id'] and receipt['operationId']==operation['id']
            assert receipt['receiptId'] and receipt['createdAt']
            assert request('POST',path,body,token)==receipt,'Duplicate request generated a new receipt'
            assert request('GET',receipt_path,token=token)==receipt
            request('POST',path,{**body,'scenario':'declined'},token,409)
            request('POST',path,{'requestId':'bad-'+request_id,'input':{'__unknown':True}},token,400)
            for scenario,status in [('declined',402 if provider['kind']=='payment' else 422),('unavailable',503)]:
                failed=request('POST',path,{**body,'requestId':scenario+'-'+request_id,'scenario':scenario},token,status)
                assert failed['mode']=='mock' and failed['success'] is False and failed['error']=='mock_'+scenario
            if provider['kind']=='payment':
                request('POST',path,{**body,'requestId':'negative-'+request_id,'input':{**body['input'],'amount':-1}},token,400)
            print('PASS mock '+provider['id']+'/'+operation['id'],flush=True)
    print('PASS mock persistence' if persistence else 'PASS mock contracts',flush=True)


if __name__=='__main__': main()
