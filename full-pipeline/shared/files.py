"""Live run files, independent of report registration in the database."""
import os
from pathlib import Path

from shared.models import safe_path

EXCLUDED_DIRECTORIES=frozenset({'.git','.venv','node_modules','dist','bin','obj','.angular','__pycache__','.pytest_cache'})
LANGUAGES={'.py':'python','.cs':'csharp','.ts':'typescript','.js':'javascript','.mjs':'javascript','.json':'json',
    '.yaml':'yaml','.yml':'yaml','.sql':'sql','.md':'markdown','.html':'html','.css':'css','.scss':'scss',
    '.xml':'xml','.csproj':'xml','.sh':'shell','.txt':'text','.svg':'xml','.webmanifest':'json','.conf':'text'}
BINARY_SUFFIXES=frozenset({'.png','.jpg','.jpeg','.gif','.webp','.ico','.woff','.woff2','.ttf','.zip','.pdf','.gz','.dll','.so'})


def restricted(relative):
    parts=Path(relative).parts
    return any((part.lower().startswith('.env') and part.lower()!='.env.example') or part.lower() in {
        'credentials.json','id_rsa','id_ed25519','.ssh'} or Path(part).suffix.lower() in {'.pem','.key','.p12','.pfx'} for part in parts)


def language(path):
    return 'dockerfile' if path.name.startswith('Dockerfile') else LANGUAGES.get(path.suffix.lower(),'text')


def kind(path):
    parts=path.parts
    if 'reports' in parts or path.suffix.lower() in {'.md','.log'}: return 'report'
    if path.suffix.lower() in {'.zip','.gz'}: return 'archive'
    if path.suffix.lower() in {'.py','.cs','.ts','.html','.css','.scss','.js','.mjs','.sql'}: return 'source'
    if path.name.startswith('.') or path.name.startswith('Dockerfile') or path.suffix.lower() in {'.json','.yml','.yaml','.conf','.xml','.csproj','.webmanifest'}: return 'config'
    return 'other'


def list_files(root):
    root=Path(root).resolve()
    result=[]
    if not root.is_dir(): return result
    for current,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in EXCLUDED_DIRECTORIES and not (Path(current)/d).is_symlink())
        for name in sorted(names):
            path=Path(current)/name
            if path.is_symlink() or not path.is_file(): continue
            relative=path.relative_to(root)
            # Verify the same boundary used for content and download endpoints.
            try:
                path=safe_path(root,relative.as_posix())
                size=path.stat().st_size
            except (OSError,ValueError): continue
            locked=restricted(relative)
            viewable=not locked and path.suffix.lower() not in BINARY_SUFFIXES
            result.append({'path':relative.as_posix(),'name':name,'size':size,'kind':kind(relative),
                'language':language(path),'viewable':viewable,'restricted':locked})
            if len(result)>20000: raise ValueError('В запуске более 20 000 файлов; уменьшите объем результата')
    return sorted(result,key=lambda item:item['path'])


def public_file(root,relative):
    path=safe_path(root,relative)
    if restricted(relative) or any(part in EXCLUDED_DIRECTORIES for part in Path(relative).parts):
        raise PermissionError('Секретные и служебные файлы недоступны для скачивания')
    if not path.is_file(): raise FileNotFoundError('Файл не найден')
    return path
