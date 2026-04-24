import ast
import inspect
import os
import re
from string import Template
from typing import Dict, List, Callable, Tuple

import click
from dotenv import load_dotenv
from openai import OpenAI
import platform

from prompt_template import react_system_prompt_template


class ReActAgent:
    def __init__(self, tools: List[Callable], model: str, project_directory: str):
        self.tools = { func.__name__: func for func in tools }
        self.model = model
        self.project_directory = project_directory
        base_url, api_key = ReActAgent.get_llm_config()
        self.base_url = base_url
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def run(self, user_input: str):
        messages = [
            {"role": "system", "content": self.render_system_prompt(react_system_prompt_template)},
            {"role": "user", "content": f"<question>{user_input}</question>"}
        ]
        tool_call_count = 0
        forced_retry_count = 0
        max_forced_retries = 8
        completion_spec = self._build_completion_spec(user_input)

        while True:

            # 请求模型
            content = self.call_model(messages)

            # 检测 Thought
            thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
            if thought_match:
                thought = thought_match.group(1)
                print(f"\n\n💭 Thought: {thought}")

            # 检测 Action（优先处理 action：即便同一轮输出了 final_answer，也先执行 action）
            action_match = re.search(r"<action>(.*?)</action>", content, re.DOTALL)
            if action_match:
                action = action_match.group(1)
                tool_name, args = self.parse_action(action)
                args = self._normalize_tool_args(tool_name, args)

                print(f"\n\n🔧 Action: {tool_name}({', '.join(args)})")
                # 只有终端命令才需要询问用户，其他的工具直接执行
                should_continue = input(f"\n\n是否继续？（Y/N）") if tool_name == "run_terminal_command" else "y"
                if should_continue.lower() != 'y':
                    print("\n\n操作已取消。")
                    return "操作被用户取消"

                try:
                    observation = self.tools[tool_name](*args)
                except Exception as e:
                    observation = f"工具执行错误：{str(e)}"
                tool_call_count += 1
                print(f"\n\n🔍 Observation：{observation}")
                obs_msg = f"<observation>{observation}</observation>"
                messages.append({"role": "user", "content": obs_msg})
                continue

            # 没有 action 的情况下，再考虑 final_answer
            final_match = re.search(r"<final_answer>(.*?)</final_answer>", content, re.DOTALL)
            if final_match:
                if tool_call_count == 0:
                    forced_retry_count += 1
                    if forced_retry_count >= max_forced_retries:
                        raise RuntimeError(
                            "模型多次未执行任何工具就尝试结束任务。\n"
                            "建议：更换模型，或在提示词中强制第一步必须 write_to_file。\n"
                            f"最后一次模型输出：{content[:500]}"
                        )
                    messages.append({
                        "role": "user",
                        "content": (
                            "<observation>禁止直接给 <final_answer>。你必须先执行至少一个工具。"
                            "如果任务涉及生成代码/文件，请先用 write_to_file 在当前项目目录下创建文件。"
                            "本轮请只输出一个可执行的 <action>，不要输出 <final_answer>。</observation>"
                        ),
                    })
                    print("\n\n⚠️ 检测到未执行工具就尝试结束，已要求模型先执行 <action>。")
                    continue

                missing_items = self._get_missing_completion_items(completion_spec)
                if missing_items:
                    missing_text = ", ".join(missing_items)
                    messages.append({
                        "role": "user",
                        "content": (
                            "<observation>任务未完成，缺少以下文件或类型："
                            f"{missing_text}。请继续使用 write_to_file 完成后再输出 <final_answer>。"
                            "</observation>"
                        ),
                    })
                    print(f"\n\n⚠️ 任务完成校验未通过，缺少：{missing_text}")
                    continue
                return final_match.group(1)

            # 既没有 action，也没有 final_answer，属于格式错误
            raise RuntimeError("模型未输出 <action> 或 <final_answer>")

    def _normalize_tool_args(self, tool_name: str, args: List[str]) -> List[str]:
        """Constrain file operations to the current project directory."""
        if tool_name not in ("read_file", "write_to_file") or not args:
            return args

        raw_path = str(args[0]).strip()
        if not raw_path:
            return args

        if os.path.isabs(raw_path):
            candidate_path = os.path.abspath(raw_path)
        else:
            candidate_path = os.path.abspath(os.path.join(self.project_directory, raw_path))

        project_root = os.path.abspath(self.project_directory)
        in_project = os.path.commonpath([project_root, candidate_path]) == project_root

        if in_project:
            args[0] = candidate_path
            return args

        redirected = os.path.abspath(os.path.join(project_root, os.path.basename(raw_path)))
        print(
            f"\n\n⚠️ 检测到越界路径：{raw_path}，"
            f"已重定向到项目目录：{redirected}"
        )
        args[0] = redirected
        return args

    def _build_completion_spec(self, user_input: str) -> Dict[str, List[str]]:
        text = user_input.lower()
        file_matches = re.findall(
            r"([a-zA-Z0-9_\-\u4e00-\u9fff]+\.(?:html|css|js|py|md|json|txt))",
            user_input,
            flags=re.IGNORECASE,
        )
        required_files = sorted({name.lower() for name in file_matches})

        required_exts: List[str] = []
        ext_keywords = [(".html", "html"), (".css", "css"), (".js", "js")]
        for ext, keyword in ext_keywords:
            if keyword in text:
                required_exts.append(ext)

        return {"required_files": required_files, "required_exts": required_exts}

    def _get_missing_completion_items(self, completion_spec: Dict[str, List[str]]) -> List[str]:
        required_files = completion_spec["required_files"]
        required_exts = completion_spec["required_exts"]
        missing: List[str] = []

        existing_paths = [
            entry.path for entry in os.scandir(self.project_directory) if entry.is_file()
        ]
        existing_file_names = {os.path.basename(path).lower() for path in existing_paths}
        existing_exts = {os.path.splitext(path)[1].lower() for path in existing_paths}

        for file_name in required_files:
            if file_name not in existing_file_names:
                missing.append(file_name)

        for ext in required_exts:
            if ext not in existing_exts:
                missing.append(f"*{ext}")

        return missing


    def get_tool_list(self) -> str:
        """生成工具列表字符串，包含函数签名和简要说明"""
        tool_descriptions = []
        for func in self.tools.values():
            name = func.__name__
            signature = str(inspect.signature(func))
            doc = inspect.getdoc(func)
            tool_descriptions.append(f"- {name}{signature}: {doc}")
        return "\n".join(tool_descriptions)

    def render_system_prompt(self, system_prompt_template: str) -> str:
        """渲染系统提示模板，替换变量"""
        tool_list = self.get_tool_list()
        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )
        return Template(system_prompt_template).substitute(
            operating_system=self.get_operating_system_name(),
            tool_list=tool_list,
            file_list=file_list
        )

    @staticmethod
    def get_llm_config() -> Tuple[str, str]:
        """
        Load base_url and api_key from environment variables.
        Priority:
        1) LLM_BASE_URL + LLM_API_KEY (generic)
        2) MINIMAX_BASE_URL + MINIMAX_API_KEY
        3) ARK_BASE_URL + ARK_API_KEY (Volcengine Ark)
        4) OPENROUTER_BASE_URL + OPENROUTER_API_KEY
        """
        load_dotenv()

        base_url = os.getenv("LLM_BASE_URL")
        api_key = os.getenv("LLM_API_KEY")
        if base_url and api_key:
            return base_url, api_key

        minimax_base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
        minimax_api_key = os.getenv("MINIMAX_API_KEY")
        if minimax_base_url and minimax_api_key:
            return minimax_base_url, minimax_api_key

        ark_base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        ark_api_key = os.getenv("ARK_API_KEY")
        if ark_base_url and ark_api_key:
            return ark_base_url, ark_api_key

        openrouter_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_base_url and openrouter_api_key:
            return openrouter_base_url, openrouter_api_key

        raise ValueError(
            "未找到可用 API 配置。请在 .env 中至少设置一组：\n"
            "1) LLM_BASE_URL + LLM_API_KEY（通用）\n"
            "2) MINIMAX_BASE_URL + MINIMAX_API_KEY（MiniMax）\n"
            "3) ARK_BASE_URL + ARK_API_KEY（火山引擎）\n"
            "4) OPENROUTER_BASE_URL + OPENROUTER_API_KEY（OpenRouter）"
        )

    @staticmethod
    def pick_model(base_url: str) -> str:
        """根据环境变量和 base_url 选择模型名/endpoint。"""
        model = (
            os.getenv("LLM_MODEL")
            or os.getenv("MINIMAX_MODEL")
            or os.getenv("ARK_MODEL")
            or os.getenv("OPENROUTER_MODEL")
        )
        if model:
            return model

        # MiniMax 默认选择更适合编程与工具调用的模型
        if "minimaxi.com" in base_url:
            return "MiniMax-M2.7"

        # 火山 Ark 必须使用 endpoint id（ep-xxx），默认不给，避免误用 openai/gpt-4o 导致 404。
        if "volces.com" in base_url:
            raise ValueError(
                "检测到当前使用火山引擎 Ark，但未配置模型。\n"
                "请在 .env 中设置 ARK_MODEL=ep-xxxx（或 LLM_MODEL=ep-xxxx）。"
            )

        return "openai/gpt-4o"

    def call_model(self, messages):
        print("\n\n正在请求模型，请稍等...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
        except Exception as e:
            err = str(e)
            if "InvalidEndpointOrModel.NotFound" in err and "volces.com" in self.base_url:
                raise RuntimeError(
                    "当前走的是火山引擎 Ark，但模型/Endpoint 不存在或无权限。\n"
                    "请在 .env 中设置 ARK_MODEL=ep-xxxx（Ark 控制台里的 Endpoint ID），"
                    "不要使用 openai/gpt-4o 这类 OpenRouter 模型名。"
                ) from e
            raise
        content = response.choices[0].message.content
        messages.append({"role": "assistant", "content": content})
        return content

    def parse_action(self, code_str: str) -> Tuple[str, List[str]]:
        match = re.match(r'(\w+)\((.*)\)', code_str, re.DOTALL)
        if not match:
            raise ValueError("Invalid function call syntax")

        func_name = match.group(1)
        args_str = match.group(2).strip()

        # 手动解析参数，特别处理包含多行内容的字符串
        args = []
        current_arg = ""
        in_string = False
        string_char = None
        i = 0
        paren_depth = 0
        
        while i < len(args_str):
            char = args_str[i]
            
            if not in_string:
                if char in ['"', "'"]:
                    in_string = True
                    string_char = char
                    current_arg += char
                elif char == '(':
                    paren_depth += 1
                    current_arg += char
                elif char == ')':
                    paren_depth -= 1
                    current_arg += char
                elif char == ',' and paren_depth == 0:
                    # 遇到顶层逗号，结束当前参数
                    args.append(self._parse_single_arg(current_arg.strip()))
                    current_arg = ""
                else:
                    current_arg += char
            else:
                current_arg += char
                if char == string_char and (i == 0 or args_str[i-1] != '\\'):
                    in_string = False
                    string_char = None
            
            i += 1
        
        # 添加最后一个参数
        if current_arg.strip():
            args.append(self._parse_single_arg(current_arg.strip()))
        
        return func_name, args
    
    def _parse_single_arg(self, arg_str: str):
        """解析单个参数"""
        arg_str = arg_str.strip()
        
        # 如果是字符串字面量
        if (arg_str.startswith('"') and arg_str.endswith('"')) or \
           (arg_str.startswith("'") and arg_str.endswith("'")):
            # 移除外层引号并处理转义字符
            inner_str = arg_str[1:-1]
            # 只处理“不会破坏 Windows 路径”的转义：
            # - \" 和 \' 用于在字符串中写引号
            # - \\ 用于写反斜杠
            #
            # 不在这里把 \n/\t/\r 转成换行/制表符/回车，
            # 因为 Windows 路径里经常出现 \t（例如 C:\tmp），会被误解析成 tab 导致路径损坏。
            # 多行内容的 \n 转换由 write_to_file 内部处理（content.replace("\\n", "\n")）。
            inner_str = inner_str.replace('\\"', '"').replace("\\'", "'")
            inner_str = inner_str.replace('\\\\', '\\')
            return inner_str
        
        # 尝试使用 ast.literal_eval 解析其他类型
        try:
            return ast.literal_eval(arg_str)
        except (SyntaxError, ValueError):
            # 如果解析失败，返回原始字符串
            return arg_str

    def get_operating_system_name(self):
        os_map = {
            "Darwin": "macOS",
            "Windows": "Windows",
            "Linux": "Linux"
        }

        return os_map.get(platform.system(), "Unknown")


def read_file(file_path):
    """用于读取文件内容"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def write_to_file(file_path, content):
    """将指定内容写入指定文件"""
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content.replace("\\n", "\n"))
    return "写入成功"

def run_terminal_command(command):
    """用于执行终端命令"""
    import subprocess
    run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if run_result.returncode == 0:
        output = run_result.stdout.strip()
        return output if output else "执行成功"
    return run_result.stderr or "命令执行失败，但没有 stderr 输出"

@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)
    load_dotenv()
    base_url, _ = ReActAgent.get_llm_config()
    model = ReActAgent.pick_model(base_url)

    tools = [read_file, write_to_file, run_terminal_command]
    agent = ReActAgent(tools=tools, model=model, project_directory=project_dir)
    print(f"当前模型：{model}")
    print(f"当前接口：{base_url}")

    task = input("请输入任务：")

    final_answer = agent.run(task)

    print(f"\n\n✅ Final Answer：{final_answer}")

if __name__ == "__main__":
    main()
