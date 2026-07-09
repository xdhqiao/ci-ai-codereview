from pathlib import Path


LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cpp": "C++",
    ".hpp": "C++ Header",
    ".cc": "C++",
    ".cs": "C#",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".ini": "INI",
    ".md": "Markdown",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
}


LANGUAGE_REVIEW_RULES: dict[str, str] = {
    "Python": (
        "重点检查异常处理、类型边界、依赖注入、同步阻塞调用、路径安全、"
        "MongoEngine/FastAPI 的资源生命周期和测试覆盖。"
    ),
    "JavaScript": (
        "重点检查异步流程、Promise 错误处理、输入校验、XSS/注入风险、"
        "包体积和运行时兼容性。"
    ),
    "TypeScript": (
        "重点检查类型收窄、any 泄漏、异步流程、React 状态一致性、"
        "运行时输入校验和构建兼容性。"
    ),
    "Go": "重点检查 goroutine 生命周期、context 传递、错误包装、并发安全和资源释放。",
    "C": "重点检查缓冲区边界、空指针、资源释放、整数溢出、格式化字符串和未定义行为。",
    "C/C++ Header": "重点检查接口契约、宏副作用、缓冲区边界、类型宽度和跨文件调用约束。",
    "C++": "重点检查对象生命周期、RAII、异常安全、越界访问、并发共享和未定义行为。",
    "C++ Header": "重点检查模板/接口契约、所有权语义、宏副作用、类型宽度和跨文件调用约束。",
    "Java": "重点检查空指针、事务边界、线程安全、异常分层、集合性能和安全输入。",
    "Rust": "重点检查生命周期/所有权假设、错误传播、unsafe、并发共享和边界条件。",
    "SQL": "重点检查注入风险、索引命中、锁范围、事务隔离和分页性能。",
    "Shell": "重点检查引号、路径空格、set -e 行为、命令注入、幂等性和可移植性。",
}


def detect_language(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix, "General")


def language_review_rules(language: str) -> str:
    if language in LANGUAGE_REVIEW_RULES:
        return LANGUAGE_REVIEW_RULES[language]
    if "TypeScript" in language:
        return LANGUAGE_REVIEW_RULES["TypeScript"]
    if "JavaScript" in language:
        return LANGUAGE_REVIEW_RULES["JavaScript"]
    return "重点检查正确性、可维护性、安全性、性能、可读性、代码风格和测试覆盖。"
