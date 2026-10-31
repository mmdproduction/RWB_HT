"""Create local secrets without overwriting an existing .env or printing secrets."""
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]
target=root/'.env'
if target.exists():
    print('.env уже существует; настройки сохранены.')
else:
    password=secrets.token_hex(24)
    content=(f'PIPELINE_WORKSPACE_ROOT={root}\nARTIFACT_ROOT={root}/artifacts\n'
        f'POSTGRES_PASSWORD={password}\nWORKER_KEY={secrets.token_hex(32)}\n'
        f'DATABASE_URL=postgresql://pipeline:{password}@127.0.0.1:55440/pipeline\n'
        'PLATFORM_API_URL=http://127.0.0.1:8100\nLLM_BASE_URL=http://127.0.0.1:14000/v1\n'
        'LLM_MODEL=qwen3.8-27b\nLLM_API_KEY=\nLLM_TIMEOUT=240\nLLM_MAX_TOKENS=12000\nPUBLIC_HOST=127.0.0.1\n')
    with target.open('x',encoding='utf-8') as file: file.write(content)
    target.chmod(0o600)
    print('.env создан. Укажите LLM_API_KEY в этом файле.')
(root/'artifacts').mkdir(exist_ok=True)
