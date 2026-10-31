"""Generation boundaries; Docker network/CSP provide runtime enforcement."""
import json
import re


def validate_generated_integrations(project,spec):
    backend=[]
    for folder in ('backend/Generated','frontend/src/app/generated'):
        for path in (project/folder).rglob('*'):
            if not path.is_file() or path.suffix not in {'.cs','.ts','.html','.css'}: continue
            text=path.read_text()
            # XML namespace identifiers are not network requests (inline SVG maps).
            network_text=re.sub(r'''(["'])http://www\.w3\.org/(?:2000/svg|1999/xlink)\1''','"local-xml-namespace"',text)
            if re.search(r'\b(?:HttpClient|HttpWebRequest|WebRequest|TcpClient|UdpClient|Socket)\b|\bProcess\s*\.\s*Start\b|\bDllImport\b|\bfetch\s*\(|(?:https?|wss?)://|(?:src|href)\s*=\s*["\']//|\bproductFetch\s*\(\s*["\']//',network_text):
                raise ValueError('Прямые внешние интеграции запрещены; используйте MockIntegrationProviders и productFetch: '+str(path.relative_to(project)))
            if path.suffix=='.cs': backend.append(text)
    if spec.externalIntegrations:
        code='\n'.join(backend)
        if 'MockIntegrationProviders' not in code or not re.search(r'\.Call\s*\(',code):
            raise ValueError('Предметный backend должен вызывать MockIntegrationProviders.Call для заявленных интеграций')


def assert_mock_runtime(project):
    config=json.loads((project/'compose.yaml').read_text())
    networks=config.get('networks',{})
    for service in ('backend','db','checks','kafka','event-consumer','browser_checks'):
        if service not in config['services']: continue
        settings=config['services'][service]
        attached=settings.get('networks',[])
        if settings.get('network_mode') or not attached or any(not networks.get(name,{}).get('internal') for name in attached):
            raise ValueError('Runtime внешней сети запрещен для '+service)
    policy=(project/'frontend/nginx.conf').read_text()
    if "connect-src 'self'" not in policy or "default-src 'self'" not in policy:
        raise ValueError('Отсутствует ограничение внешних запросов браузера')
