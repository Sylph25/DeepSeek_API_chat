"""
DeepSeek Chat 主程序
====================
从 config.yaml 加载配置，启动交互式聊天会话。
支持命令行参数覆盖配置项。

用法:
    python main.py                     # 使用 config.yaml 启动
    python main.py --model deepseek-chat  # 临时切换模型
    python main.py --no-thinking        # 关闭思维链显示
    python main.py --no-stream          # 关闭流式输出
    python main.py --single "你好"      # 单次对话模式（非交互）
"""

import os
import sys
import argparse
import yaml
from deepseekchat import DeepSeekChat
from env_utils import ensure_api_key, resolve_config


def load_config(config_path: str = None) -> dict:
    """
    加载 YAML 配置文件

    :param config_path: 配置文件路径，None 则使用默认位置
    :returns: 配置字典
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')

    if not os.path.exists(config_path):
        print(f"[错误] 配置文件不存在: {config_path}")
        print("[信息] 请创建 config.yaml，或参考 config.yaml 模板。")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def merge_args_into_config(config: dict, args: argparse.Namespace) -> dict:
    """将命令行参数合并到配置字典中"""
    if args.api_key:
        config.setdefault('api', {})['api_key'] = args.api_key
    if args.base_url:
        config.setdefault('api', {})['base_url'] = args.base_url
    if args.model:
        config.setdefault('model', {})['name'] = args.model
    if args.temperature is not None:
        config.setdefault('model', {})['temperature'] = args.temperature
    if args.reasoning_effort:
        config.setdefault('model', {})['reasoning_effort'] = args.reasoning_effort
    if args.no_thinking:
        config.setdefault('model', {})['thinking_enabled'] = False
    if args.system_prompt:
        config.setdefault('chat', {})['system_prompt'] = args.system_prompt
    if args.no_history:
        config.setdefault('chat', {})['save_history'] = False
    return config


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='DeepSeek Chat - 智能对话客户端',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                              # 正常交互模式
  python main.py --model deepseek-chat         # 使用其他模型
  python main.py --temperature 1.2             # 调高创造性
  python main.py --no-thinking                 # 关闭思维链显示
  python main.py --single "介绍一下DeepSeek"   # 单次问答
  python main.py --config my_config.yaml       # 使用自定义配置
        """
    )

    # 配置文件
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='指定配置文件路径 (默认: ./config.yaml)')

    # API 参数
    parser.add_argument('--api-key', type=str, default=None,
                        help='DeepSeek API 密钥')
    parser.add_argument('--base-url', type=str, default=None,
                        help='API 基础地址')

    # 模型参数
    parser.add_argument('--model', '-m', type=str, default=None,
                        help='模型名称')
    parser.add_argument('--temperature', '-t', type=float, default=None,
                        help='温度参数 (0.0 ~ 2.0)')
    parser.add_argument('--reasoning-effort', type=str, default=None,
                        choices=['low', 'medium', 'high'],
                        help='推理努力程度')
    parser.add_argument('--no-thinking', action='store_true',
                        help='禁用思维链显示')

    # 对话参数
    parser.add_argument('--system-prompt', '-s', type=str, default=None,
                        help='系统提示词')
    parser.add_argument('--no-history', action='store_true',
                        help='不保存对话历史')

    # 模式参数
    parser.add_argument('--single', type=str, default=None,
                        help='单次对话模式：发送一条消息后退出')
    parser.add_argument('--save', type=str, default=None,
                        help='单次模式时指定保存对话的文件名标识')

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 1. 加载配置
    config = load_config(args.config)

    # 2. 合并命令行参数
    config = merge_args_into_config(config, args)

    # 3. 确保 API 密钥可用（首次运行会提示输入）
    api_key = ensure_api_key(config)
    if api_key:
        config.setdefault('api', {})['api_key'] = api_key

    # 4. 创建聊天实例
    chat = DeepSeekChat(config)

    # 4. 运行模式
    if args.single:
        # 单次对话模式
        print(f"{chat.c_info}>>> 单次对话模式{chat.c_reset}")
        chat.send_message(args.single)
        if args.save:
            path = chat.save_chat_history(args.save)
            print(f"{chat.c_info}对话已保存至: {path}{chat.c_reset}")
    else:
        # 交互模式
        chat.run_interactive()


if __name__ == '__main__':
    main()
