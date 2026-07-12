import json
from typing import Any

from app.core.config import Settings
from app.services.rules import review_rules_for


BASE_SYSTEM_PROMPT = """你是资深代码审核专家，正在执行 CI 代码审核。
目标是发现真实、可定位、可修复的问题，避免泛泛而谈。
你必须兼顾正确性、性能、安全、可读性和代码风格五个维度。
severity 必须是 1 到 5 的整数，1 表示轻微，5 表示最严重。
只评论当前目标文件；其他文件及其 diff 只能用于验证上下文，不能成为评论对象。
增量审核优先评论新增或修改后的代码；删除校验、锁、资源释放等代码导致行为回归时，
可以评论删除块之后首个受影响的存活代码行，并在 evidence 中明确说明被删除的保护逻辑。
不得直接评论已删除代码、无关未修改代码或纯主观风格偏好。
上下文不足时先调用工具核验，不得把猜测作为 issue 提交。
"""


PLAN_OUTPUT_SCHEMA = """只输出 JSON，不要输出 Markdown：
{
  "comment": "本代码块整体评价",
  "change_summary": "本次变更的目的和影响范围",
  "risk_level": "high|medium|low",
  "checkpoints": [
    {
      "focus": "需要核验的具体风险点",
      "severity": "high|medium|low",
      "lines": "可能相关的变更后行号",
      "why": "风险成立时的影响",
      "rule_id": "命中的规则编号，可为空",
      "tool_guidance": [
        {"name": "code_search|read_file|file_read_diff|file_find|find_definition|find_references|call_graph", "reason": "为何需要上下文", "arguments": {}}
      ]
    }
  ],
  "logic_score": 0-100,
  "performance_score": 0-100,
  "security_score": 0-100,
  "readable_score": 0-100,
  "code_style_score": 0-100
}
"""


MAIN_OUTPUT_SCHEMA = """最终必须通过 code_comment 工具提交问题，并在审核完成后通过 task_done 工具结束任务。
每个问题必须包含 type、severity、description、suggestion、issue_line_numbers、existing_code、evidence。
type 只能使用 logic、performance、security、readability、code_style。
issue_line_numbers 使用变更后文件中的行号，多个行号用英文逗号分隔。
existing_code 必须是目标文件或 diff 中可以直接匹配的短代码片段；evidence 说明为什么这是本次变更引入或暴露的真实问题。
可以额外提供 suggestion_code 表示建议替换后的代码片段。
优先在一次 code_comment 调用的 comments 数组中批量提交已经确认的问题。提交评论后仍必须调用 task_done(state="DONE")。
如果当前模型或网关不支持工具调用，则直接输出 JSON：
{"issues":[{"type":"security","severity":5,"description":"问题描述","suggestion":"修复建议","issue_line_numbers":"12","existing_code":"strcpy(dst, input);","suggestion_code":"snprintf(dst, sizeof(dst), \"%s\", input);","evidence":"新增行直接使用无边界拷贝","confidence_level":0.8}]}
"""


RELOCATION_OUTPUT_SCHEMA = """只输出 JSON，不要输出 Markdown：
{
  "issues": [
    {
      "issue_id": 1,
      "issue_line_numbers": "12",
      "relocation_status": "unchanged|relocated|failed",
      "relocation_description": "解释为什么保留、修正或无法定位",
      "existing_code": "从 diff 中逐字复制的最小连续代码片段",
      "evidence_match_status": "matched|partial|missing",
      "evidence_match_score": 0.0-1.0,
      "confidence_level": 0.0-1.0
    }
  ]
}
"""


FILTER_OUTPUT_SCHEMA = """只输出 JSON，不要输出 Markdown：
{
  "decisions": [
    {
      "issue_id": 1,
      "issue_show": true,
      "filter_status": "kept|filtered",
      "filter_reason": "保留或过滤的原因",
      "counter_evidence": "只有过滤时填写：diff 中可直接证伪该 issue 的代码证据",
      "evidence_match_status": "matched|partial|missing",
      "evidence_match_score": 0.0-1.0,
      "confidence_level": 0.0-1.0
    }
  ]
}
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
                    "query_name": {"type": "string"},
                    "case_sensitive": {"type": "boolean", "default": False},
                },
                "required": ["query_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read_diff",
            "description": "批量读取当前提交中任意变更文件的 diff，只用于验证当前目标文件的问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path_array": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path_array"],
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
                    "search_text": {"type": "string"},
                    "file_patterns": {"type": "array", "items": {"type": "string"}},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "use_perl_regexp": {"type": "boolean", "default": False},
                },
                "required": ["search_text"],
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
            "name": "find_definition",
            "description": "通过 AST 语义索引查找函数、方法、类型或其他符号的定义/声明位置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "file_path": {"type": "string", "description": "可选，当前文件路径，用于优先排序同文件定义。"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_references",
            "description": "通过 AST 语义索引查找符号在仓库中的引用，可用于确认调用方、数据使用点和影响范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "file_path": {"type": "string", "description": "可选，只返回该仓库相对路径中的引用。"},
                    "include_declarations": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_graph",
            "description": "查询函数或方法的入向/出向调用关系，最多展开三层，用于验证跨文件调用链。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"], "default": "both"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_comment",
            "description": "批量提交已经确认、可定位且有证据的当前文件代码审核问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "comments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["logic", "performance", "security", "readability", "code_style"]},
                                "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                                "description": {"type": "string"},
                                "suggestion": {"type": "string"},
                                "issue_line_numbers": {"type": "string"},
                                "existing_code": {"type": "string"},
                                "suggestion_code": {"type": "string"},
                                "evidence": {"type": "string"},
                                "rule_id": {"type": "string"},
                                "confidence_level": {"type": "number"}
                            },
                            "required": ["type", "severity", "description", "suggestion", "issue_line_numbers", "existing_code", "evidence"]
                        }
                    }
                },
                "required": ["comments"],
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
                    "state": {"type": "string", "enum": ["DONE", "FAILED"]},
                    "summary": {"type": "string"},
                },
                "required": ["state"],
            },
        },
    },
]


def build_plan_messages(
    file_name: str,
    language: str,
    diff_lines: list[str],
    full_code: str,
    change_files_context: str = "",
    related_files_context: str = "",
    static_analysis_context: str = "",
    background: str = "",
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            (
                "## 阶段任务指令\n执行 plan_task：理解代码变更，给出结构化风险检查点、建议的上下文工具调用、"
                "本代码块整体评论和五个维度评分。检查点必须落到本次新增/修改代码，不要把可能性写成已确认问题。"
            ),
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n规则 JSON：{review_rules_for(file_name, language, settings)}",
            (
                "## 当前文件业务背景（Background）\n"
                "这是当前文件独立对应的需求与业务约束。只能依据已提供内容审核，不得补造未声明需求。\n"
                + (background or "（未提供当前文件的业务背景）")
            ),
            "## 本次提交的其他变更文件\n" + (change_files_context or "（无）"),
            (
                "## 确定性相关文件上下文\n"
                "这些文件由路径、配对关系和显式引用确定。规划时优先核验它们，但只能评论当前目标文件。\n"
                + (related_files_context or "（未发现确定性相关文件）")
            ),
            (
                "## 独立静态分析证据\n"
                "这些结果来自独立分析器，只能作为待核验证据；检查数据流和实际代码后再形成评论，不得机械复制。\n"
                + (static_analysis_context or "（无相关静态分析结果）")
            ),
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
    plan_guidance: str,
    change_files_context: str = "",
    related_files_context: str = "",
    static_analysis_context: str = "",
    background: str = "",
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            (
                "## 阶段任务指令\n执行 main_task：逐项核验 plan_task 的风险检查点，并独立扫查遗漏风险。"
                "上下文不足时调用工具；不要重复使用相同参数调用同一只读工具。"
                "涉及符号定义、调用方或跨文件控制流时，优先使用 find_definition、find_references、call_graph 核验。"
                "提交 code_comment 前，必须确认 issue_line_numbers 能定位到变更后的新增/修改代码，"
                "并提供逐字可匹配的 existing_code 和事实 evidence。完成后必须调用 task_done。"
            ),
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n规则 JSON：{review_rules_for(file_name, language, settings)}",
            (
                "## 当前文件业务背景（Background）\n"
                "使用该文件独立需求判断实现是否满足契约；背景未声明的行为不得推断为缺陷。\n"
                + (background or "（未提供当前文件的业务背景）")
            ),
            "## 本次提交的其他变更文件\n" + (change_files_context or "（无）"),
            (
                "## 确定性相关文件上下文\n"
                "以下候选已由工程逻辑筛选。用它们验证接口、调用方和契约；Issue 仍必须锚定当前文件的变更行。\n"
                + (related_files_context or "（未发现确定性相关文件）")
            ),
            (
                "## 独立静态分析证据\n"
                "逐项验证这些 finding。确认属实时可用其 rule_id 和位置增强 evidence；不成立时不要提交。\n"
                + (static_analysis_context or "（无相关静态分析结果）")
            ),
            "## plan_task 结构化结论\n" + plan_guidance,
            "## 代码变更\n" + "\n".join(diff_lines),
            "## 目标文件完整代码\n" + full_code,
            "## 输出格式强约束\n" + MAIN_OUTPUT_SCHEMA,
        ]
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_relocation_messages(
    file_name: str,
    language: str,
    diff_lines: list[str],
    full_code: str,
    issues: list[dict[str, Any]],
    background: str = "",
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            (
                "## 阶段任务指令\n执行 RE_LOCATION_TASK：这些 issue 已经通过本地连续代码匹配但定位失败。"
                "从 diff 中逐字复制能支撑该评论的最小连续新增代码作为 existing_code，并给出变更后行号。"
                "不得改写代码；无法找到时 relocation_status 必须为 failed。"
            ),
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n规则 JSON：{review_rules_for(file_name, language, settings)}",
            "## 当前文件业务背景（Background）\n" + (background or "（未提供）"),
            "## 待校准 issues\n" + json.dumps({"issues": issues}, ensure_ascii=False, indent=2),
            "## 代码变更\n" + "\n".join(diff_lines),
            "## 目标文件完整代码\n" + _numbered_full_code(full_code),
            "## 输出格式强约束\n" + RELOCATION_OUTPUT_SCHEMA,
        ]
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_review_filter_messages(
    file_name: str,
    language: str,
    diff_lines: list[str],
    full_code: str,
    issues: list[dict[str, Any]],
    background: str = "",
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    user_content = "\n\n".join(
        [
            (
                "## 阶段任务指令\n执行 REVIEW_FILTER_TASK：你是反证事实核查器。"
                "只有当当前 diff 提供直接反证、足以证明 issue 的核心事实错误时才过滤；"
                "仅仅无法从 diff 验证、需要跨文件或运行时上下文，必须保留。"
                "过滤时必须在 counter_evidence 中指出直接反证。"
            ),
            f"## 文件与规则上下文\n文件：{file_name}\n语言：{language}\n规则 JSON：{review_rules_for(file_name, language, settings)}",
            "## 当前文件业务背景（Background）\n" + (background or "（未提供）"),
            "## 待过滤 issues\n" + json.dumps({"issues": issues}, ensure_ascii=False, indent=2),
            "## 代码变更\n" + "\n".join(diff_lines),
            "## 目标文件完整代码\n" + _numbered_full_code(full_code),
            "## 输出格式强约束\n" + FILTER_OUTPUT_SCHEMA,
        ]
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_batch_dedup_messages(comments: list[dict[str, Any]]) -> list[dict[str, str]]:
    system_content = """你负责给同一个 full-scan 批次中的近重复审核问题分组。
只把描述同一根因、同一严重度、同一证据模式的问题放入同一组；仅仅类别相同不能合并。
每个输入 id 必须且只能出现一次。分组只建立关联，不过滤任何文件中的独立问题实例。
只输出 JSON：{"groups":[{"members":["c-0"]},{"members":["c-1","c-3"]}]}。
"""
    return [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": "## 批次 issues\n" + json.dumps(comments, ensure_ascii=False, indent=2),
        },
    ]


def build_memory_compression_messages(context: str) -> list[dict[str, str]]:
    system_content = """你负责压缩代码审核工具对话，使 main_task 能继续而不丢失关键推理状态。
只总结已经出现的事实，不新增问题。输出纯文本并按以下标题组织，空标题可省略：
### Confirmed Issues
### Tool Conclusions
### Completed Checks
### Pending Checks
### Current Focus
保留文件路径、issue 类型/严重度、关键工具结论和仍需核验的假设；不要复制大段代码。
"""
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": context},
    ]


def build_project_summary_messages(
    project_stats: dict[str, Any],
    issues: list[dict[str, Any]],
) -> list[dict[str, str]]:
    system_content = """你是 full-scan 的项目级高级审核人。
根据已经完成证据定位和反证过滤的 issue，提炼跨文件根因、最高风险、模块热点和低成本高收益修复项。
不要新增输入中不存在的问题，不要逐条复述，不要把被过滤或未完成文件视为已审核。
输出简洁 Markdown，使用以下可选小节：Top Issues、Module Hotspots、Cross-Cutting Concerns、Quick Wins、Coverage Gaps。
"""
    user_content = "\n\n".join(
        [
            "## 扫描统计\n" + json.dumps(project_stats, ensure_ascii=False, indent=2),
            "## 已确认 issues\n" + json.dumps(issues, ensure_ascii=False, indent=2),
        ]
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _numbered_full_code(full_code: str) -> str:
    return "\n".join(f"{index:>6}  {line}" for index, line in enumerate(full_code.splitlines(), start=1))
