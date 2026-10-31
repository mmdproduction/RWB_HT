import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.settings import Settings
from worker.llm import ModelClient,ModelError

try:
    value,usage=ModelClient(Settings.from_env()).ask('Return JSON only.','Return {"ready":true}.')
    print('Qwen ready:',value.get('ready') is True,'usage:',usage)
except ModelError as error:
    print(str(error));sys.exit(1)
