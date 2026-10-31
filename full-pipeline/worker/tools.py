import json
import os
from pathlib import Path
import signal
import subprocess
import time

from shared.models import safe_path


class ToolError(RuntimeError):
    pass


def apply_patch(root:Path,patch:dict):
    files=patch.get('files')
    if not isinstance(files,list) or not 1<=len(files)<=24:
        raise ValueError('Ожидается files: от 1 до 24 файлов одного компонента')
    if sum(len(item['content']) for item in files if isinstance(item,dict) and isinstance(item.get('content'),str))>300000:
        raise ValueError('Слишком большой пакет исходников')
    prepared=[]
    seen=set()
    for item in files:
        if not isinstance(item,dict): raise ValueError('Описание исходника должно быть JSON object')
        path=item.get('path','')
        target=safe_path(root,path)
        if path in seen: raise ValueError('Повтор пути файла')
        seen.add(path)
        permitted=(path.startswith('backend/Generated/') and path.endswith('.cs')) or (
            path.startswith('frontend/src/app/generated/') and Path(path).suffix in {'.ts','.html','.css'})
        if not permitted: raise ValueError('Модель может менять только предметные исходники в Generated/generated')
        content=item.get('content')
        if not isinstance(content,str) or not content.strip() or len(content)>100000:
            raise ValueError('Пустой или слишком большой исходник')
        if target.name=='Extensions.cs' and ('class GeneratedExtensions' not in content or 'Map(WebApplication app)' not in content):
            raise ValueError('Сохраните контракт GeneratedExtensions.Map(WebApplication app)')
        if target.name=='generated-panel.ts' and 'class GeneratedPanel' not in content:
            raise ValueError('Сохраните экспорт GeneratedPanel')
        prepared.append((target,content))
    for target,content in prepared:
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(content,encoding='utf-8')
    return [str(target.relative_to(root)) for target,_ in prepared]


def run_command(command:list[str],cwd:Path,timeout:float,env:dict|None=None,cancel=None):
    # No shell and no inheritance of model/platform credentials into build tools.
    child={key:value for key,value in os.environ.items() if key in {
        'PATH','HOME','USER','LANG','LC_ALL','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_CONFIG','TMPDIR'}}
    child.update(env or {})
    started=time.monotonic()
    with subprocess.Popen(command,cwd=cwd,env=child,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          text=True,start_new_session=True,errors='replace') as process:
        while True:
            try:
                output,_=process.communicate(timeout=min(0.5,max(0.01,timeout-(time.monotonic()-started))))
                break
            except subprocess.TimeoutExpired:
                expired=time.monotonic()-started>=timeout
                cancelled=cancel is not None and cancel.is_set()
                if expired or cancelled:
                    os.killpg(process.pid,signal.SIGKILL)
                    output,_=process.communicate()
                    raise ToolError(('Command cancelled after lease loss' if cancelled else f'Command timeout after {timeout}s')+'\n'+output[-12000:]) from None
    return {'command':command,'returnCode':process.returncode,'durationSeconds':round(time.monotonic()-started,3),'output':output}


def write_json(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def command_json(output,required_keys):
    """Docker pull/npm notices can surround the command's JSON document."""
    decoder=json.JSONDecoder()
    for match in __import__('re').finditer(r'\{',output):
        try: value,_=decoder.raw_decode(output[match.start():])
        except ValueError: continue
        if isinstance(value,dict) and set(required_keys)<=value.keys(): return value
    raise ValueError('Command did not return the required JSON report')
