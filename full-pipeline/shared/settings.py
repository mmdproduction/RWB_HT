from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str = ''
    worker_key: str = ''
    artifact_root: Path = Path('artifacts')
    api_url: str = 'http://127.0.0.1:8100'
    llm_base_url: str = 'http://127.0.0.1:14000/v1'
    llm_api_key: str = ''
    llm_model: str = 'qwen3.8-27b'
    llm_timeout: float = 180.0
    llm_max_tokens: int = 12000
    llm_429_max_retries: int = 4
    llm_429_wait_seconds: float = 180.0
    lease_seconds: int = 120
    heartbeat_seconds: float = 15.0
    command_timeout: int = 900
    public_host: str = '127.0.0.1'
    cors_origins: str = 'http://127.0.0.1:8090,http://localhost:8090,http://localhost:4200'

    @property
    def secrets(self):
        return (self.llm_api_key, self.worker_key, self.database_url)

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            database_url=os.getenv('DATABASE_URL', ''),
            worker_key=os.getenv('WORKER_KEY', ''),
            artifact_root=Path(os.getenv('ARTIFACT_ROOT', 'artifacts')).resolve(),
            api_url=os.getenv('PLATFORM_API_URL', 'http://127.0.0.1:8100').rstrip('/'),
            llm_base_url=os.getenv('LLM_BASE_URL', 'http://127.0.0.1:14000/v1').rstrip('/'),
            llm_api_key=os.getenv('LLM_API_KEY', ''),
            llm_model=os.getenv('LLM_MODEL', 'qwen3.8-27b'),
            llm_timeout=float(os.getenv('LLM_TIMEOUT', '180')),
            llm_max_tokens=int(os.getenv('LLM_MAX_TOKENS', '12000')),
            llm_429_max_retries=int(os.getenv('LLM_429_MAX_RETRIES', '4')),
            llm_429_wait_seconds=float(os.getenv('LLM_429_WAIT_SECONDS', '180')),
            lease_seconds=int(os.getenv('LEASE_SECONDS', '120')),
            heartbeat_seconds=float(os.getenv('HEARTBEAT_SECONDS', '15')),
            command_timeout=int(os.getenv('COMMAND_TIMEOUT', '900')),
            public_host=os.getenv('PUBLIC_HOST', '127.0.0.1'),
            cors_origins=os.getenv('CORS_ORIGINS', cls.cors_origins),
        )
