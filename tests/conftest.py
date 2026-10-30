import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 测试统一强制使用 mock 引擎，不依赖外部服务与真实凭证，
# 也避免 auto 模式在无 gpt-researcher 环境下产生歧义。
os.environ["RESEARCHER_MODE"] = "mock"
os.environ["RESEARCHER_TIMEOUT_SECONDS"] = "10"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

# Disable both production .env readers before test modules import main/service.
import config

config.Settings.model_config["env_file"] = None
config.get_settings.cache_clear()
