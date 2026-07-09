from app.services.language import language_review_rules


BASE_SYSTEM_PROMPT = """你是资深代码审核专家，正在执行 CI 代码审核。
目标是发现真实、可定位、可修复的问题，避免泛泛而谈。
你必须兼顾正确性、性能、安全、可读性和代码风格五个维度。
severity 必须是 1 到 5 的整数，1 表示轻微，5 表示最严重。
"""


PLAN_OUTPUT_SCHEMA = """只输出 JSON，不要输出 Markdown：
{
  "comment": "本代码块整体评价",
  "logic_score": 0-100,
  "performance_score": 0-100,
  "security_score": 0-100,
  "readable_score": 0-100,
  "code_style_score": 0-100
}
"""


MAIN_OUTPUT_SCHEMA = """最终必须通过 code_comment 工具提交问题，或通过 task_done 工具声明无问题。
每个问题必须包含 type、severity、description、suggestion、issue_line_numbers。
type 只能使用 logic、performance、security、readability、code_style。
issue_line_numbers 使用变更后文件中的行号，多个行号用英文逗号分隔。
如果当前模型或网关不支持工具调用，则直接输出 JSON：
{"issues":[{"type":"security","severity":5,"description":"问题描述","suggestion":"修复建议","issue_line_numbers":"12","confidence_level":0.8}]}
"""


MAIN_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "file_find",
            "description": "按文件路径或文件名查找目标代码目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "regex": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read_diff",
            "description": "读取当前审核文件的 diff 内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_search",
            "description": "在目标代码目录中按关键字或正则搜索代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "regex": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取目标仓库中的文件内容，可指定起止行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "read_file 的兼容别名，用于贴近 OCR 工具命名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_comment",
            "description": "提交一个明确的代码审核问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "issue_line_numbers": {"type": "string"},
                    "confidence_level": {"type": "number"},
                },
                "required": ["type", "severity", "description", "suggestion", "issue_line_numbers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_done",
            "description": "确认当前代码块审核完成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                },
            },
        },
    },
]


def build_plan_messages(file_name: str, language: str, diff_lines: list[str], full_code: str) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            "## 阶段任务指令\n执行 plan_task：先理解代码变更，给出本代码块整体评论和五个维度评分。",
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n语言专项规则：{language_review_rules(language)}",
            "## 代码变更\n" + "\n".join(diff_lines),
            "## 目标文件完整代码\n" + full_code,
            "## 输出格式强约束\n" + PLAN_OUTPUT_SCHEMA,
        ]
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_main_messages(
    file_name: str,
    language: str,
    diff_lines: list[str],
    full_code: str,
    plan_comment: str,
) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            "## 阶段任务指令\n执行 main_task：围绕 plan_task 的判断继续审查，必要时使用工具读取上下文。",
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n语言专项规则：{language_review_rules(language)}",
            "## plan_task 结论\n" + plan_comment,
            "## 代码变更\n" + "\n".join(diff_lines),
            "## 目标文件完整代码\n" + full_code,
            "## 输出格式强约束\n" + MAIN_OUTPUT_SCHEMA,
        ]
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
