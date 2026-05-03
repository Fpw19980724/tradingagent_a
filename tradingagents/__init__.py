import os

os.environ.setdefault("PYTHONUTF8", "1")
# 设置环境变量以解决 IPv6 连接超时和 mini_racer 崩溃问题
# 使用直接赋值而非 setdefault，确保这些变量始终被正确设置
os.environ["NO_PROXY"] = "*"
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""
os.environ["LANGCHAIN_OPENAI_TCP_KEEPALIVE"] = "0"

# 加载 .env 文件中的 API 密钥等配置
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .platform import TradingPlatform, create_default_platform

__all__ = [
    "TradingPlatform",
    "create_default_platform",
]
