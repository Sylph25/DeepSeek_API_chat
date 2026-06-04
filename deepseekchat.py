"""
DeepSeek Chat 模块
==================
可独立运行，也可被 main.py 调用。
通过参数或 config 字典来配置所有选项。
"""

import os
import json
from datetime import datetime
from openai import OpenAI
from env_utils import resolve_config, get_api_key, get_base_url


# 【兼容Windows】开启终端ANSI颜色支持
if os.name == 'nt':
    os.system('color')


class DeepSeekChat:
    """DeepSeek 聊天客户端封装类"""

    def __init__(self, config: dict):
        """
        初始化聊天客户端

        :param config: 配置字典，结构参考 config.yaml
        """
        # 解析配置中的 ${VAR} 占位符
        resolved = resolve_config(config)
        api_cfg = resolved.get('api', {})
        model_cfg = resolved.get('model', {})
        chat_cfg = resolved.get('chat', {})
        ui_cfg = resolved.get('ui', {})

        # 从环境变量 / .env 补充 API 密钥（如果占位符未解析到值）
        _api_key = api_cfg.get('api_key') or get_api_key()
        _base_url = api_cfg.get('base_url', 'https://api.deepseek.com') or get_base_url()

        # --- API 客户端 ---
        self.client = OpenAI(
            api_key=_api_key,
            base_url=_base_url
        )

        # --- 模型参数 ---
        self.model_name = model_cfg.get('name', 'deepseek-v4-flash')
        self.reasoning_effort = model_cfg.get('reasoning_effort', 'high')
        self.temperature = model_cfg.get('temperature', 0.7)
        self.max_tokens = model_cfg.get('max_tokens')  # None 表示不限制
        self.thinking_enabled = model_cfg.get('thinking_enabled', True)

        # --- 对话参数 ---
        self.system_prompt = chat_cfg.get(
            'system_prompt',
            '你是一个专业、耐心的helper，帮助用户解答问题，提供信息，并且在对话中保持友好和专业的态度。当需要展示代码时，请使用标准 Markdown 代码块格式，明确标注语言类型（如 ```python、```javascript、```html、```css、```bash 等），并在代码前后用空行分隔，使代码块清晰可辨。'
        )
        self.save_history = chat_cfg.get('save_history', True)
        history_dir_rel = chat_cfg.get('history_dir', 'chat_history')
        # 始终相对于脚本所在目录，防止工作目录不同导致位置错误
        self.history_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), history_dir_rel
        )

        # --- 记忆系统参数 ---
        mem_cfg = config.get('memory', {})
        self.memory_enabled = mem_cfg.get('enabled', True)
        self.memory_file = mem_cfg.get('file', 'memories.json')
        self.memory_auto_apply = mem_cfg.get('auto_apply', True)

        # --- UI 颜色 ---
        self.c_user = ui_cfg.get('color_user', '\033[93m')
        self.c_assistant = ui_cfg.get('color_assistant', '\033[92m')
        self.c_text = ui_cfg.get('color_text', '\033[97m')
        self.c_reset = ui_cfg.get('color_reset', '\033[0m')
        self.c_info = ui_cfg.get('color_info', '\033[96m')
        self.show_token_usage = ui_cfg.get('show_token_usage', False)

        # --- 记忆存储（内存中） ---
        self.memories: list[str] = []

        # --- 初始化消息列表 ---
        self.messages = []
        self._rebuild_messages()

        # --- 会话历史文件（每次运行自动创建一个） ---
        self._session_history_file: str | None = None
        if self.save_history:
            self._init_session_history_file()

    # ------------------------------------------------------------------
    def _build_extra_body(self) -> dict:
        """构造 extra_body 参数"""
        if self.thinking_enabled:
            return {"thinking": {"type": "enabled"}}
        return {}

    # ------------------------------------------------------------------
    # 记忆系统
    # ------------------------------------------------------------------
    def _memories_path(self) -> str:
        """获取记忆文件的完整路径"""
        cfg_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.isabs(self.memory_file):
            return self.memory_file
        return os.path.join(cfg_dir, self.memory_file)

    def _load_memories(self) -> list[str]:
        """从文件加载所有记忆"""
        path = self._memories_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def _save_memories(self, memories: list[str]):
        """保存记忆列表到文件"""
        path = self._memories_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(memories, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"{self.c_info}[记忆] 保存失败: {e}{self.c_reset}")

    def _build_system_messages(self) -> list[dict]:
        """
        根据 system_prompt + 记忆构建完整的 system 消息列表
        返回消息列表，可包含多条 system 消息
        """
        system_msgs = [{"role": "system", "content": self.system_prompt}]

        if self.memory_enabled and self.memory_auto_apply and self.memories:
            mem_text = "## 你必须严格遵守的用户长期记忆要求：\n"
            for i, mem in enumerate(self.memories, 1):
                mem_text += f"{i}. {mem}\n"
            mem_text += "请严格遵守以上所有要求，不得违背。"
            system_msgs.append({"role": "system", "content": mem_text})

        return system_msgs

    def _rebuild_messages(self):
        """重新构建整个 messages 列表（保留历史对话，更新 system 消息）"""
        # 保留已有的非 system 消息（对话历史）
        old_conversation = [m for m in getattr(self, 'messages', [])
                            if m['role'] != 'system']

        # 加载记忆（仅在首次初始化时）
        if not getattr(self, '_memories_loaded', False):
            self.memories = self._load_memories()
            self._memories_loaded = True

        # 重新构建 system 消息
        self.messages = self._build_system_messages()
        self.messages.extend(old_conversation)

    # ------------------------------------------------------------------
    # 记住 / 忘记 命令辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    def _is_remember_cmd(text: str) -> bool:
        """判断是否为「记住：xxx」命令"""
        return text.startswith("记住：") or text.startswith("记住:")

    @staticmethod
    def _is_forget_cmd(text: str) -> bool:
        """判断是否为「忘记：xxx」命令"""
        return text.startswith("忘记：") or text.startswith("忘记:")

    @staticmethod
    def _extract_remember_content(text: str) -> str:
        """提取「记住：」后面的内容"""
        for prefix in ("记住：", "记住:"):
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return ""

    @staticmethod
    def _extract_forget_content(text: str) -> str:
        """提取「忘记：」后面的内容"""
        for prefix in ("忘记：", "忘记:"):
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return ""

    def _add_memory(self, content: str):
        """添加一条记忆（去重）并持久化"""
        # 检查是否已存在相同内容
        for existing in self.memories:
            if existing.strip() == content:
                print(f"{self.c_info}[记忆] 该要求已存在，跳过{self.c_reset}")
                return

        self.memories.append(content)
        self._save_memories(self.memories)
        self._rebuild_messages()
        print(f"{self.c_info}[记忆] 已记住: {content}{self.c_reset}")
        print(f"{self.c_info}[记忆] 当前共 {len(self.memories)} 条长期记忆，将在后续对话中自动生效{self.c_reset}")

        # 立即通知 AI 这条新记忆（插入一条 system 消息增强即时效果）
        self.messages.append({
            "role": "system",
            "content": f"[系统即时指令] 用户刚刚要求你记住（必须严格遵守）: {content}"
        })

    def _remove_memory(self, content_or_index: str):
        """通过内容或序号删除记忆"""
        removed = False

        # 尝试按序号删除
        if content_or_index.isdigit():
            idx = int(content_or_index) - 1
            if 0 <= idx < len(self.memories):
                removed_item = self.memories.pop(idx)
                removed = True
                print(f"{self.c_info}[记忆] 已删除第 {idx + 1} 条: {removed_item}{self.c_reset}")
        else:
            # 按内容匹配删除
            new_memories = [m for m in self.memories if m.strip() != content_or_index]
            if len(new_memories) < len(self.memories):
                removed = True
                self.memories = new_memories
                print(f"{self.c_info}[记忆] 已删除: {content_or_index}{self.c_reset}")

        if removed:
            self._save_memories(self.memories)
            self._rebuild_messages()
            print(f"{self.c_info}[记忆] 剩余 {len(self.memories)} 条{self.c_reset}")
        else:
            print(f"{self.c_info}[记忆] 未找到匹配的记忆: {content_or_index}{self.c_reset}")

    def _show_memories(self):
        """显示所有记忆"""
        if not self.memories:
            print(f"{self.c_info}[记忆] 当前没有任何长期记忆{self.c_reset}")
            print(f"{self.c_info}[记忆] 使用「记住：xxx」来添加要求{self.c_reset}")
            return

        print(f"{self.c_info}===== 长期记忆 ({len(self.memories)} 条) ====={self.c_reset}")
        for i, mem in enumerate(self.memories, 1):
            print(f"{self.c_info}{i}. {mem}{self.c_reset}")
        print(f"{self.c_info}用法:{self.c_reset}")
        print(f"{self.c_info}  添加: 记住：你的要求{self.c_reset}")
        print(f"{self.c_info}  删除: 忘记：序号 或 忘记：具体内容{self.c_reset}")

    # ------------------------------------------------------------------
    # 会话历史文件管理
    # ------------------------------------------------------------------
    def _init_session_history_file(self):
        """
        在 history 目录下创建一个以时间命名的会话历史文件，
        写入文件头信息。
        """
        os.makedirs(self.history_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"session_{timestamp}.md"
        self._session_history_file = os.path.join(self.history_dir, filename)

        header = (
            f"# DeepSeek Chat 会话记录\n"
            f"\n"
            f"- **开始时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **模型**: {self.model_name}\n"
            f"- **文件**: {filename}\n"
            f"\n"
            f"---\n"
            f"\n"
        )
        with open(self._session_history_file, 'w', encoding='utf-8') as f:
            f.write(header)

        print(f"{self.c_info}[历史] 会话记录文件: {self._session_history_file}{self.c_reset}")

    def _append_to_session_file(self, role: str, content: str):
        """将一条问答记录追加到当前会话历史文件中"""
        if not self._session_history_file:
            return
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        label = "用户" if role == "user" else "DeepSeek"
        entry = (
            f"### [{label}] {timestamp}\n"
            f"\n"
            f"{content}\n"
            f"\n"
        )
        with open(self._session_history_file, 'a', encoding='utf-8') as f:
            f.write(entry)

    # ------------------------------------------------------------------
    def send_message(self, user_input: str) -> str:
        """
        发送一条用户消息并获取 AI 回复（流式输出到终端）
        会自动处理「记住：xxx」「忘记：xxx」「/memories」等内置命令。

        :param user_input: 用户输入文本
        :returns: AI 回复的完整文本，如果是内置命令则返回空字符串
        """

        # --- 内置命令：查看记忆 ---
        if user_input.lower() == "/memories":
            self._show_memories()
            return ""

        # --- 内置命令：记住 ---
        if self.memory_enabled and self._is_remember_cmd(user_input):
            content = self._extract_remember_content(user_input)
            if content:
                self._add_memory(content)
            return ""

        # --- 内置命令：忘记 ---
        if self.memory_enabled and self._is_forget_cmd(user_input):
            content = self._extract_forget_content(user_input)
            if content:
                self._remove_memory(content)
            return ""

        # 添加用户消息到上下文
        self.messages.append({"role": "user", "content": user_input})

        # 保存用户提问到会话历史文件
        self._append_to_session_file("user", user_input)

        # 构造请求参数
        kwargs = {
            "model": self.model_name,
            "messages": self.messages,
            "stream": True,
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens

        extra_body = self._build_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body

        # 发送请求并流式输出
        response = self.client.chat.completions.create(**kwargs)

        print(f"\n{self.c_assistant}DeepSeek：{self.c_reset}", end="", flush=True)
        ai_response = ""
        usage_info = None

        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                content = delta.content
                ai_response += content
                print(f"{self.c_text}{content}{self.c_reset}", end="", flush=True)
            # 收集 token 使用信息（只在最后一个 chunk 中）
            if chunk.usage:
                usage_info = chunk.usage

        print()  # 换行

        # 添加到上下文
        self.messages.append({"role": "assistant", "content": ai_response})

        # 保存 AI 回复到会话历史文件
        self._append_to_session_file("assistant", ai_response)

        # 显示 token 用量
        if self.show_token_usage and usage_info:
            print(f"{self.c_info}[Token 用量: ↑{usage_info.prompt_tokens} / "
                  f"↓{usage_info.completion_tokens} / "
                  f"总计 {usage_info.total_tokens}]{self.c_reset}")

        return ai_response

    # ------------------------------------------------------------------
    def save_chat_history(self, title: str = None) -> str:
        """
        将当前对话历史保存到文件

        :param title: 文件名标识（可选）
        :returns: 保存的文件路径
        """
        if not self.save_history:
            return ""

        os.makedirs(self.history_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        label = f"_{title}" if title else ""
        filename = f"chat{label}_{timestamp}.json"
        filepath = os.path.join(self.history_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)

        return filepath

    # ------------------------------------------------------------------
    def clear_context(self):
        """清空对话上下文（保留 system prompt 和记忆）"""
        self._rebuild_messages()
        print(f"{self.c_info}对话上下文已清空，长期记忆已保留{self.c_reset}")

    # ------------------------------------------------------------------
    def run_interactive(self):
        """启动交互式对话循环"""
        cmds = "exit/quit 退出 | /clear 清空上下文 | /save 保存历史"
        if self.memory_enabled:
            cmds += " | 记住：... | 忘记：... | /memories 查看记忆"
        print(f"{self.c_info}=== DeepSeek 交互模式 ==={self.c_reset}")
        print(f"{self.c_info}{cmds}{self.c_reset}")

        # 启动时提示已有记忆
        if self.memory_enabled and self.memories:
            print(f"{self.c_info}已加载 {len(self.memories)} 条长期记忆{self.c_reset}")

        while True:
            try:
                user_input = input(f"\n{self.c_user}我:{self.c_reset}")

                # --- 退出 ---
                if user_input.lower() in ["exit", "quit"]:
                    print(f"{self.c_info}对话结束！{self.c_reset}")
                    if self.save_history:
                        if self._session_history_file:
                            print(f"{self.c_info}会话记录已保存至: {self._session_history_file}{self.c_reset}")
                        if len(self.messages) > 1:
                            path = self.save_chat_history()
                            print(f"{self.c_info}JSON 备份已保存至: {path}{self.c_reset}")
                    break

                # --- /clear ---
                if user_input.lower() == "/clear":
                    self.clear_context()
                    continue

                # --- /save ---
                if user_input.lower() == "/save":
                    path = self.save_chat_history()
                    print(f"{self.c_info}对话已保存至: {path}{self.c_reset}")
                    continue

                if not user_input.strip():
                    continue

                # --- 发送消息 ---
                self.send_message(user_input)

            except KeyboardInterrupt:
                print(f"\n{self.c_info}用户中断{self.c_reset}")
                break
            except Exception as e:
                print(f"\n{self.c_info}错误: {e}{self.c_reset}")
                break


# ------------------------------------------------------------------
# 独立运行入口（向后兼容）
# ------------------------------------------------------------------
if __name__ == '__main__':
    import yaml

    cfg_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    else:
        # 默认配置
        config = {
            'api': {'api_key': 'API_KEY', 'base_url': 'https://api.deepseek.com'},
            'model': {'name': 'deepseek-v4-flash', 'reasoning_effort': 'high', 'thinking_enabled': True},
        }

    chat = DeepSeekChat(config)
    chat.run_interactive()
    