import json
from pathlib import Path
import sys
import urllib.request

path=Path(sys.argv[1] if len(sys.argv)>1 else 'examples/tasks.md')
request=urllib.request.Request('http://127.0.0.1:8100/api/runs',data=json.dumps({'requirements':path.read_text()}).encode(),headers={'Content-Type':'application/json'},method='POST')
print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request).read().decode())
