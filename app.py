"""
DeepSeek Chat WebUI
===================
基于 Flask 的浏览器聊天界面。
支持多会话管理、Markdown 历史记录读写、流式输出。

用法:
    python app.py
    然后打开浏览器访问 http://localhost:5000
"""

import os
import sys
import re
import json
import yaml
from datetime import datetime
from threading import Lock
from openai import OpenAI
from flask import (
    Flask, render_template, request, jsonify, Response, stream_with_context
)
from env_utils import resolve_config, get_api_key, get_base_url, save_api_key_to_env, save_base_url_to_env, ensure_api_key

# ===========================================================================
# 配置加载
# ===========================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PyInstaller 打包后，持久化数据（历史记录、记忆）放到 exe 所在目录
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = BASE_DIR

CONFIG_PATH = os.path.join(DATA_DIR, 'config.yaml')


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# 确保后续所有 yaml 操作指定 UTF-8 编码
def _save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


config = resolve_config(load_config())
api_cfg = config.get('api', {})
model_cfg = config.get('model', {})
chat_cfg = config.get('chat', {})
mem_cfg = config.get('memory', {})

# 确保 .env 文件存在（若不存在则创建模板）
from env_utils import _is_valid_api_key, ENV_FILE, PLACEHOLDER_API_KEY
import os as _os
if not _os.path.exists(ENV_FILE):
    with open(ENV_FILE, 'w', encoding='utf-8') as _f:
        _f.write(f"# DeepSeek Chat 环境变量配置\n")
        _f.write(f"# 请将 YOUR-API-KEY 替换为你的 DeepSeek API 密钥\n")
        _f.write(f"{ENV_KEY_API_KEY}={PLACEHOLDER_API_KEY}\n")
        _f.write(f"{ENV_KEY_BASE_URL}=https://api.deepseek.com\n")
    print(f"[信息] 已创建环境变量模板: {ENV_FILE}")

# 从环境变量 / .env 补充 API 密钥（如果占位符未解析到值）
_api_key = api_cfg.get('api_key') or get_api_key()
_base_url = api_cfg.get('base_url', 'https://api.deepseek.com') or get_base_url()

# 检查 API 密钥是否有效
if not _is_valid_api_key(_api_key):
    _api_key = None
    print("[警告] API 密钥未配置。请通过 WebUI 设置页面或编辑 .env 文件配置。")

# --- OpenAI 客户端 ---
client = OpenAI(
    api_key=_api_key,
    base_url=_base_url
) if _api_key else None

# --- 模型参数 ---
MODEL_NAME = model_cfg.get('name', 'deepseek-v4-flash')
REASONING_EFFORT = model_cfg.get('reasoning_effort', 'high')
TEMPERATURE = model_cfg.get('temperature', 0.7)
MAX_TOKENS = model_cfg.get('max_tokens')
THINKING_ENABLED = model_cfg.get('thinking_enabled', True)

# 可运行时切换的模型（用于 WebUI 下拉菜单）
_current_model = MODEL_NAME

# --- 对话参数 ---
SYSTEM_PROMPT = chat_cfg.get(
    'system_prompt',
    '你是一个专业、耐心的helper，帮助用户解答问题，提供信息，并且在对话中保持友好和专业的态度。当需要展示代码时，请使用标准 Markdown 代码块格式，明确标注语言类型（如 ```python、```javascript、```html、```css、```bash 等），并在代码前后用空行分隔，使代码块清晰可辨。'
)
SAVE_HISTORY = chat_cfg.get('save_history', True)
history_dir_rel = chat_cfg.get('history_dir', 'history')
HISTORY_DIR = os.path.join(DATA_DIR, history_dir_rel)

# --- 记忆参数 ---
MEMORY_ENABLED = mem_cfg.get('enabled', True)
MEMORY_FILE = mem_cfg.get('file', 'memories.json')
MEMORY_AUTO_APPLY = mem_cfg.get('auto_apply', True)

# ===========================================================================
# Flask 应用
# ===========================================================================
app = Flask(__name__)

# ===========================================================================
# 会话管理
# ===========================================================================
# _sessions: { session_id: { "id": str, "title": str, "messages": list, "file": str } }
_sessions: dict = {}
_sessions_lock = Lock()
_next_id = 0


def _memories_path() -> str:
    if os.path.isabs(MEMORY_FILE):
        return MEMORY_FILE
    return os.path.join(DATA_DIR, MEMORY_FILE)


def _load_memories() -> list[str]:
    path = _memories_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _save_memories(memories: list[str]):
    """保存记忆列表到文件"""
    path = _memories_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[记忆] 保存失败: {e}")


def _build_system_messages() -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if MEMORY_ENABLED and MEMORY_AUTO_APPLY:
        memories = _load_memories()
        if memories:
            mem_text = "## 你必须严格遵守的用户长期记忆要求：\n"
            for i, mem in enumerate(memories, 1):
                mem_text += f"{i}. {mem}\n"
            mem_text += "请严格遵守以上所有要求，不得违背。"
            msgs.append({"role": "system", "content": mem_text})
    return msgs


def _get_title_from_messages(messages: list) -> str:
    """从消息列表中提取标题（第一条用户消息的前 30 个字）"""
    for m in messages:
        if m['role'] == 'user':
            text = m['content'].strip()
            if len(text) > 30:
                return text[:30] + '...'
            return text
    return '新对话'


def _parse_md_session(filepath: str) -> list[dict] | None:
    """
    解析 Markdown 历史文件，提取消息列表。
    格式：
        ### [用户] 时间戳
        内容
        ### [DeepSeek] 时间戳
        内容
    返回消息列表，或 None 解析失败
    """
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except IOError:
        return None

    messages = []
    # 匹配 ### [用户] 或 ### [DeepSeek] 块
    pattern = r'### \[(用户|DeepSeek)\].*?\n(.*?)(?=\n### \[|\Z)'
    for match in re.finditer(pattern, content, re.DOTALL):
        role_label = match.group(1)
        text = match.group(2).strip()
        role = 'user' if role_label == '用户' else 'assistant'
        if text:
            messages.append({"role": role, "content": text})
    return messages


def _list_session_files() -> list[dict]:
    """扫描 history 目录下的所有 session Markdown 文件"""
    if not os.path.exists(HISTORY_DIR):
        return []
    files = []
    for fname in sorted(os.listdir(HISTORY_DIR), reverse=True):
        if fname.startswith('session_') and fname.endswith('.md'):
            fpath = os.path.join(HISTORY_DIR, fname)
            stat = os.stat(fpath)
            # 从文件名提取时间
            time_str = fname.replace('session_', '').replace('.md', '')
            try:
                dt = datetime.strptime(time_str, '%Y%m%d_%H%M%S')
                display_time = dt.strftime('%Y-%m-%d %H:%M')
            except ValueError:
                display_time = time_str
            files.append({
                'filename': fname,
                'path': fpath,
                'time': display_time,
                'size': stat.st_size,
            })
    return files


def _create_new_session(first_message: str = None) -> dict:
    """创建一个新会话"""
    global _next_id
    with _sessions_lock:
        _next_id += 1
        sid = str(_next_id)
        messages = _build_system_messages()
        title = '新对话'

        # 生成文件路径
        os.makedirs(HISTORY_DIR, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"session_{timestamp}.md"
        filepath = os.path.join(HISTORY_DIR, filename)

        # 写文件头
        header = (
            f"# DeepSeek Chat 会话记录\n"
            f"\n"
            f"- **开始时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **模型**: {MODEL_NAME}\n"
            f"- **文件**: {filename}\n"
            f"\n"
            f"---\n"
            f"\n"
        )
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(header)

        session = {
            'id': sid,
            'title': title,
            'messages': messages,
            'file': filepath,
            'filename': filename,
        }
        _sessions[sid] = session
        return session


def _load_or_create_session(session_id: str | None,
                             filename: str | None = None) -> dict:
    """
    根据 ID 或文件名加载会话，不存在则创建新会话。
    """
    # 优先按 ID 查找内存中的会话
    if session_id and session_id in _sessions:
        return _sessions[session_id]

    # 按文件名从磁盘加载
    if filename:
        filepath = os.path.join(HISTORY_DIR, filename)
        msgs = _parse_md_session(filepath)
        if msgs is not None:
            system_msgs = _build_system_messages()
            full_msgs = system_msgs + msgs
            title = _get_title_from_messages(msgs)
            global _next_id
            with _sessions_lock:
                _next_id += 1
                sid = str(_next_id)
            session = {
                'id': sid,
                'title': title,
                'messages': full_msgs,
                'file': filepath,
                'filename': filename,
            }
            _sessions[sid] = session
            return session

    # 创建新会话
    return _create_new_session()


def _append_to_md_file(filepath: str, role: str, content: str):
    """将一条问答追加到 Markdown 历史文件"""
    if not filepath or not os.path.exists(filepath):
        return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    label = "用户" if role == "user" else "DeepSeek"
    entry = (
        f"### [{label}] {timestamp}\n"
        f"\n"
        f"{content}\n"
        f"\n"
    )
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(entry)


# ===========================================================================
# Flask 路由
# ===========================================================================

@app.route('/')
def index():
    """渲染主页面"""
    return render_template('chat.html', model_name=MODEL_NAME)


@app.route('/api/config')
def get_config():
    """返回前端需要的配置信息"""
    return jsonify({
        'model': _current_model,
        'models': ['deepseek-v4-flash', 'deepseek-v4-pro'],
    })


@app.route('/api/balance')
def get_balance():
    """查询 DeepSeek API 账户余额"""
    import requests as http_requests
    api_key = api_cfg.get('api_key') or get_api_key()
    if not api_key:
        return jsonify({'error': 'API 密钥未配置'}), 400

    currency = request.args.get('currency', '')
    url = "https://api.deepseek.com/user/balance"
    params = {}
    if currency:
        params['currency'] = currency

    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    try:
        resp = http_requests.get(url, headers=headers, params=params, timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/model', methods=['GET', 'POST'])
def switch_model():
    """获取或切换当前使用的模型"""
    global _current_model
    if request.method == 'POST':
        data = request.get_json() or {}
        model = data.get('model', '')
        if model in ['deepseek-v4-flash', 'deepseek-v4-pro']:
            _current_model = model
            return jsonify({'model': _current_model, 'success': True})
        return jsonify({'error': f'不支持的模型: {model}'}), 400
    return jsonify({'model': _current_model})


@app.route('/api/sessions')
def list_sessions():
    """列出所有历史会话文件"""
    files = _list_session_files()
    return jsonify({'sessions': files})


@app.route('/api/sessions/load', methods=['POST'])
def load_session():
    """加载指定历史会话"""
    data = request.get_json() or {}
    filename = data.get('filename', '')
    if not filename:
        return jsonify({'error': '缺少 filename 参数'}), 400

    session = _load_or_create_session(None, filename)
    # 返回给前端时过滤掉 system 消息
    chat_msgs = [m for m in session['messages'] if m['role'] != 'system']
    return jsonify({
        'id': session['id'],
        'title': session['title'],
        'messages': chat_msgs,
        'filename': session['filename'],
    })


@app.route('/api/sessions/new', methods=['POST'])
def new_session():
    """创建新会话"""
    session = _create_new_session()
    return jsonify({
        'id': session['id'],
        'title': session['title'],
        'messages': [],
        'filename': session['filename'],
    })


@app.route('/api/sessions/<filename>', methods=['DELETE'])
def delete_session(filename):
    """删除指定历史会话文件"""
    # 防止路径穿越
    safe_name = os.path.basename(filename)
    if not safe_name.startswith('session_') or not safe_name.endswith('.md'):
        return jsonify({'error': '无效的文件名'}), 400

    filepath = os.path.join(HISTORY_DIR, safe_name)
    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404

    try:
        # 从内存中移除关联的会话
        for sid, sess in list(_sessions.items()):
            if sess.get('filename') == safe_name:
                del _sessions[sid]
        # 删除文件
        os.remove(filepath)
        return jsonify({'success': True, 'filename': safe_name})
    except OSError as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@app.route('/api/chat/<session_id>', methods=['POST'])
def chat_stream(session_id):
    """
    发送消息并返回流式 SSE 响应。
    如果 session_id 为 'new'，则自动创建新会话。
    """
    data = request.get_json() or {}
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': '消息不能为空'}), 400

    # 获取或创建会话
    session = _load_or_create_session(session_id)
    session_id = session['id']

    # 如果会话还没有标题（刚创建），用第一条消息设为标题
    if session['title'] == '新对话' and user_message:
        title_text = user_message[:30] + '...' if len(user_message) > 30 else user_message
        session['title'] = title_text

    # 添加用户消息
    session['messages'].append({"role": "user", "content": user_message})
    _append_to_md_file(session['file'], 'user', user_message)

    def generate():
        ai_response = ""

        # 构造请求参数
        kwargs = {
            "model": _current_model,
            "messages": session['messages'],
            "stream": True,
        }
        if REASONING_EFFORT:
            kwargs["reasoning_effort"] = REASONING_EFFORT
        if TEMPERATURE is not None:
            kwargs["temperature"] = TEMPERATURE
        if MAX_TOKENS is not None:
            kwargs["max_tokens"] = MAX_TOKENS

        extra_body = {}
        if THINKING_ENABLED:
            extra_body["thinking"] = {"type": "enabled"}
        if extra_body:
            kwargs["extra_body"] = extra_body

        if client is None:
            yield f"data: {json.dumps({'error': 'API 密钥未配置，请在设置页面配置后再试', 'done': True})}\n\n"
            return

        try:
            response = client.chat.completions.create(**kwargs)
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    content = delta.content
                    ai_response += content
                    yield f"data: {json.dumps({'content': content, 'done': False})}\n\n"

            # 保存 AI 回复
            session['messages'].append({"role": "assistant", "content": ai_response})
            _append_to_md_file(session['file'], 'assistant', ai_response)

            yield f"data: {json.dumps({'content': '', 'done': True, 'session_id': session_id, 'title': session['title']})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


# ===========================================================================
# 设置页面 API
# ===========================================================================

@app.route('/api/settings', methods=['GET', 'POST'])
def settings_api():
    """获取或保存配置"""
    if request.method == 'POST':
        data = request.get_json() or {}
        try:
            # 重新加载当前配置
            cfg = load_config()

            # 敏感信息（API 密钥、地址）保存到 .env，不写入 config.yaml
            if 'api_key' in data:
                save_api_key_to_env(data['api_key'])
            if 'base_url' in data:
                save_base_url_to_env(data['base_url'])

            # 更新配置（非敏感字段写入 config.yaml）
            if 'model_name' in data:
                cfg.setdefault('model', {})['name'] = data['model_name']
            if 'reasoning_effort' in data:
                cfg.setdefault('model', {})['reasoning_effort'] = data['reasoning_effort']
            if 'temperature' in data:
                cfg.setdefault('model', {})['temperature'] = float(data['temperature'])
            if 'max_tokens' in data:
                val = data['max_tokens']
                cfg.setdefault('model', {})['max_tokens'] = int(val) if val not in (None, '', 'null') else None
            if 'thinking_enabled' in data:
                cfg.setdefault('model', {})['thinking_enabled'] = bool(data['thinking_enabled'])
            if 'system_prompt' in data:
                cfg.setdefault('chat', {})['system_prompt'] = data['system_prompt']
            if 'save_history' in data:
                cfg.setdefault('chat', {})['save_history'] = bool(data['save_history'])
            if 'memory_enabled' in data:
                cfg.setdefault('memory', {})['enabled'] = bool(data['memory_enabled'])
            if 'memory_auto_apply' in data:
                cfg.setdefault('memory', {})['auto_apply'] = bool(data['memory_auto_apply'])
            if 'ui_theme' in data:
                cfg.setdefault('ui', {})['theme'] = data['ui_theme']

            # 写回 YAML（不含 API 密钥）
            _save_config(cfg)

            # 重新加载配置到内存（通过 resolve_config 解析占位符）
            global config, api_cfg, model_cfg, chat_cfg, mem_cfg
            global client, MODEL_NAME, REASONING_EFFORT, TEMPERATURE, MAX_TOKENS, THINKING_ENABLED
            global SYSTEM_PROMPT, SAVE_HISTORY, MEMORY_ENABLED, MEMORY_AUTO_APPLY, _current_model
            config = resolve_config(load_config())
            api_cfg = config.get('api', {})
            model_cfg = config.get('model', {})
            chat_cfg = config.get('chat', {})
            mem_cfg = config.get('memory', {})

            _api_key = api_cfg.get('api_key') or get_api_key()
            _base_url = api_cfg.get('base_url', 'https://api.deepseek.com') or get_base_url()
            client = OpenAI(
                api_key=_api_key,
                base_url=_base_url
            )
            MODEL_NAME = model_cfg.get('name', 'deepseek-v4-flash')
            REASONING_EFFORT = model_cfg.get('reasoning_effort', 'high')
            TEMPERATURE = model_cfg.get('temperature', 0.7)
            MAX_TOKENS = model_cfg.get('max_tokens')
            THINKING_ENABLED = model_cfg.get('thinking_enabled', True)
            _current_model = MODEL_NAME
            SYSTEM_PROMPT = chat_cfg.get('system_prompt', '')
            SAVE_HISTORY = chat_cfg.get('save_history', True)
            MEMORY_ENABLED = mem_cfg.get('enabled', True)
            MEMORY_AUTO_APPLY = mem_cfg.get('auto_apply', True)

            return jsonify({'success': True, 'message': '配置已保存，部分设置将在下次对话时生效'})
        except Exception as e:
            return jsonify({'error': f'保存失败: {str(e)}'}), 500

    # GET - 返回当前配置（API 密钥从环境变量 /.env 读取，不暴露原始占位符）
    cfg = resolve_config(load_config())
    api_cfg = cfg.get('api', {})
    # 如果配置中仍未解析到密钥，尝试从环境变量获取
    from env_utils import _is_valid_api_key
    if not _is_valid_api_key(api_cfg.get('api_key')):
        api_cfg['api_key'] = get_api_key() or ''
    if not _is_valid_api_key(api_cfg.get('api_key')):
        api_cfg['api_key'] = ''
    if not api_cfg.get('base_url'):
        api_cfg['base_url'] = get_base_url() or 'https://api.deepseek.com'
    return jsonify({
        'api': api_cfg,
        'model': cfg.get('model', {}),
        'chat': cfg.get('chat', {}),
        'memory': cfg.get('memory', {}),
        'ui': cfg.get('ui', {}),
    })


# ===========================================================================
# 记忆系统 API
# ===========================================================================

@app.route('/api/memories', methods=['GET', 'POST'])
def memories_api():
    """获取或保存长期记忆列表"""
    if request.method == 'POST':
        data = request.get_json() or {}
        memories = data.get('memories', [])
        if not isinstance(memories, list):
            return jsonify({'error': 'memories 必须是数组'}), 400
        # 确保每项都是字符串
        memories = [str(m) for m in memories]
        _save_memories(memories)
        return jsonify({'success': True, 'memories': memories, 'count': len(memories)})

    # GET - 返回所有记忆
    memories = _load_memories()
    return jsonify({'memories': memories, 'count': len(memories)})


@app.route('/api/memories/<int:index>', methods=['DELETE'])
def delete_memory(index):
    """删除指定序号的记忆（1-based）"""
    memories = _load_memories()
    if 0 <= index - 1 < len(memories):
        removed = memories.pop(index - 1)
        _save_memories(memories)
        return jsonify({'success': True, 'removed': removed, 'memories': memories})
    return jsonify({'error': '序号无效'}), 404


# ===========================================================================
# 入口
# ===========================================================================
if __name__ == '__main__':
    print(f"🌐 DeepSeek Chat WebUI 已启动")
    print(f"📋 模型: {MODEL_NAME}")
    print(f"🔗 请访问: http://localhost:5000")
    print(f"📁 历史记录目录: {HISTORY_DIR}")
    app.run(debug=True, host='0.0.0.0', port=5000)
