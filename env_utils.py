"""
环境变量工具模块
================
统一管理 API 密钥等敏感信息，支持从以下来源（优先级从高到低）：
1. 系统环境变量 (os.environ)
2. .env 文件（项目根目录）
3. config.yaml 中的原始值（含占位符时跳过）

用法:
    from env_utils import resolve_config, ensure_api_key, save_api_key_to_env

    # 解析配置中的 ${VAR} 占位符
    config = resolve_config(raw_config)

    # CLI 模式下确保 API Key 存在
    api_key = ensure_api_key(config)
"""

import os
import re
import sys

# .env 文件路径（项目根目录）
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

# 环境变量名常量
ENV_KEY_API_KEY = 'DEEPSEEK_API_KEY'
ENV_KEY_BASE_URL = 'DEEPSEEK_BASE_URL'

# 默认占位符值（新建 .env 时写入，避免暴露真实密钥）
PLACEHOLDER_API_KEY = 'YOUR-API-KEY'


def _is_valid_api_key(key: str | None) -> bool:
    """检查 API 密钥是否有效（不为空、不是占位符、不以 ${ 开头）"""
    if not key:
        return False
    if key == PLACEHOLDER_API_KEY:
        return False
    if key.startswith('${'):
        return False
    return True


def _load_dotenv() -> dict:
    """解析 .env 文件，返回键值对字典"""
    env_vars = {}
    if not os.path.exists(ENV_FILE):
        return env_vars
    try:
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key:
                        env_vars[key] = value
    except IOError:
        pass
    return env_vars


def _save_dotenv(env_vars: dict):
    """将键值对写入 .env 文件"""
    os.makedirs(os.path.dirname(ENV_FILE) or '.', exist_ok=True)
    # 读取已有内容，保留注释和格式
    lines = []
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except IOError:
            lines = []

    # 更新或追加每个变量
    written_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if '=' in stripped and not stripped.startswith('#'):
            key = stripped.split('=', 1)[0].strip()
            if key in env_vars:
                new_lines.append(f"{key}={env_vars[key]}\n")
                written_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in env_vars.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")

    try:
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    except IOError as e:
        print(f"[env_utils] 写入 .env 失败: {e}")


def get_api_key() -> str | None:
    """
    获取有效的 API 密钥，优先级：
    1. 系统环境变量 DEEPSEEK_API_KEY
    2. .env 文件中的 DEEPSEEK_API_KEY
    如果值为默认占位符 YOUR-API-KEY 则视为未设置。
    """
    # 1. 系统环境变量
    key = os.environ.get(ENV_KEY_API_KEY)
    if _is_valid_api_key(key):
        return key
    # 2. .env 文件
    env_vars = _load_dotenv()
    key = env_vars.get(ENV_KEY_API_KEY)
    if _is_valid_api_key(key):
        return key
    return None


def get_base_url() -> str | None:
    """获取 API 基础地址（可选）"""
    url = os.environ.get(ENV_KEY_BASE_URL)
    if url:
        return url
    env_vars = _load_dotenv()
    return env_vars.get(ENV_KEY_BASE_URL)


def save_api_key_to_env(api_key: str):
    """将 API 密钥保存到 .env 文件"""
    env_vars = _load_dotenv()
    env_vars[ENV_KEY_API_KEY] = api_key
    _save_dotenv(env_vars)


def save_base_url_to_env(base_url: str):
    """将 API 地址保存到 .env 文件"""
    env_vars = _load_dotenv()
    env_vars[ENV_KEY_BASE_URL] = base_url
    _save_dotenv(env_vars)


def _resolve_placeholder(value: str) -> str:
    """
    解析字符串中的 ${VAR} 占位符。
    从系统环境变量或 .env 文件中查找。
    如果找不到对应变量，返回原字符串。
    """
    def _replace(match):
        var_name = match.group(1)
        # 从系统环境变量查找
        val = os.environ.get(var_name)
        if val:
            return val
        # 从 .env 文件查找
        env_vars = _load_dotenv()
        return env_vars.get(var_name, match.group(0))

    return re.sub(r'\$\{(\w+)\}', _replace, value)


def resolve_config(config: dict) -> dict:
    """
    解析配置字典中的所有字符串值，替换 ${VAR} 占位符。
    返回新的配置字典（不修改原对象）。
    """
    import copy

    def _resolve(obj):
        if isinstance(obj, str):
            return _resolve_placeholder(obj)
        elif isinstance(obj, dict):
            return {k: _resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve(item) for item in obj]
        return obj

    return _resolve(copy.deepcopy(config))


def ensure_api_key(config: dict) -> str | None:
    """
    确保 API 密钥可用。
    检查顺序：config 中的 api_key → 环境变量 → .env 文件。
    如果都没有，在 CLI 模式下提示用户输入并保存到 .env。
    返回有效的 API 密钥，或 None。
    """
    # 先从配置中获取（可能已经是解析后的值）
    api_key = config.get('api', {}).get('api_key', '')
    if _is_valid_api_key(api_key):
        return api_key

    # 从环境变量 / .env 获取
    api_key = get_api_key()
    if api_key:
        return api_key

    # 如果 .env 文件不存在，创建一个带占位符的模板
    if not os.path.exists(ENV_FILE):
        _save_dotenv({ENV_KEY_API_KEY: PLACEHOLDER_API_KEY,
                      ENV_KEY_BASE_URL: 'https://api.deepseek.com'})
        print(f"\n[信息] 已创建环境变量文件: {ENV_FILE}")
        print(f"   请将 {ENV_KEY_API_KEY}=YOUR-API-KEY 中的 YOUR-API-KEY")
        print(f"   替换为你的实际 DeepSeek API 密钥。")

    # CLI 模式：交互式询问
    if sys.stdin.isatty():
        print("\n" + "=" * 50)
        print("[首次运行检测]")
        print("=" * 50)
        current = get_api_key()
        if current and _is_valid_api_key(current):
            return current
        print("当前 API 密钥为占位符，请输入真实密钥。")
        api_key = input("请输入你的 DeepSeek API Key (sk-...): ").strip()
        if api_key:
            save_api_key_to_env(api_key)
            print("[成功] API 密钥已保存到 .env 文件")
            return api_key
        print("\n[警告] 未输入 API 密钥，部分功能将不可用。")
        print(f"   请编辑 {ENV_FILE} 文件，将 {ENV_KEY_API_KEY} 设置为你实际的密钥。")

    return None
