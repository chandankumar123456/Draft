from azure.ai.projects.models import FunctionTool


def make_tool(
    name: str,
    description: str,
    properties: dict,
    required: list[str],
) -> FunctionTool:
    """
    Create an Azure FunctionTool definition.
    """

    return FunctionTool(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        strict=True,
    )


# ============================================================
# FILESYSTEM
# ============================================================

list_files_tool = make_tool(
    "list_files",
    "List files and directories inside the given directory. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "directory": {
            "type": "string",
            "description": "Directory path to inspect. Optional; defaults to the current directory.",
        }
    },
    [],
)


list_directory_tree_tool = make_tool(
    "list_directory_tree",
    "Return a recursive directory tree up to the specified depth. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Directory path to inspect. Optional; defaults to the current directory.",
        },
        "depth": {
            "type": "integer",
            "description": "Maximum recursion depth. Optional; defaults to 3.",
        },
    },
    [],
)


read_file_tool = make_tool(
    "read_file",
    "Read the contents of a text file, optionally restricting the returned line range. Returns a structured result "
    '{"success", "data", "message", "error"}; on success data.content holds 1-based numbered lines '
    '("<n>: <text>"). start_line/end_line are inclusive. Content is truncated with a "truncated" '
    "flag when the file exceeds the read limit.",
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "start_line": {
            "type": ["integer", "null"],
            "description": "1-based starting line (inclusive). Use null to start from the beginning.",
        },
        "end_line": {
            "type": ["integer", "null"],
            "description": "1-based ending line (inclusive). Use null to read until the end.",
        },
    },
    ["path"],
)


write_file_tool = make_tool(
    "write_file",
    "Write text content to a file. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path of the file to write.",
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file.",
        },
        "overwrite": {
            "type": "boolean",
            "description": "Whether an existing file may be overwritten. Optional; defaults to True.",
        },
    },
    ["path", "content"],
)


get_file_info_tool = make_tool(
    "get_file_info",
    "Return metadata about a file or directory. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to inspect.",
        }
    },
    ["path"],
)


create_directory_tool = make_tool(
    "create_directory",
    "Create a directory and any missing parent directories. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Directory path to create.",
        }
    },
    ["path"],
)


delete_file_tool = make_tool(
    "delete_file",
    "Delete a file. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path of the file to delete.",
        }
    },
    ["path"],
)


delete_directory_tool = make_tool(
    "delete_directory",
    "Delete a directory. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Directory path to delete.",
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to recursively delete the directory contents. Optional; defaults to False.",
        },
    },
    ["path"],
)


move_file_tool = make_tool(
    "move_file",
    "Move a file or directory to another location. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "source": {
            "type": "string",
            "description": "Source path.",
        },
        "destination": {
            "type": "string",
            "description": "Destination path.",
        },
    },
    ["source", "destination"],
)


copy_file_tool = make_tool(
    "copy_file",
    "Copy a file or directory to another location. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "source": {
            "type": "string",
            "description": "Source path.",
        },
        "destination": {
            "type": "string",
            "description": "Destination path.",
        },
    },
    ["source", "destination"],
)


# ============================================================
# CODE SEARCH
# ============================================================

search_code_tool = make_tool(
    "search_code",
    "Search source code files for a plain-text substring. Returns a structured result "
    '{"success", "data", "message", "error"}; results include metadata files_scanned, files_skipped and '
    "truncated. Matching is case-insensitive by default (case_sensitive=True makes it exact-case); extensions are "
    'bare names like "py" (leading dots optional).',
    {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Text to search for. Must not be empty.",
        },
        "path": {
            "type": "string",
            "description": "Directory to search in. Searches recursively. Optional; defaults to the current directory.",
        },
        "extensions": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Optional list of file extensions to include, e.g. [\"py\", \"js\"]. Use null for the default code extension list.",
        },
        "case_sensitive": {
            "type": "boolean",
            "description": "Whether the search should be case-sensitive. Optional; defaults to False.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of matches to return. Optional; defaults to 200.",
        },
    },
    ["query"],
)


grep_tool = make_tool(
    "grep",
    "Search files under a path for lines matching a regular expression. Returns a structured result "
    '{"success", "data", "message", "error"}; results include metadata files_scanned, files_skipped and truncated. '
    "No extension filter is applied (every file type is searched).",
    {
        "pattern": {
            "type": "string",
            "description": "Regular expression pattern.",
        },
        "path": {
            "type": "string",
            "description": "Directory to search in. Searches recursively. Optional; defaults to the current directory.",
        },
        "ignore_case": {
            "type": "boolean",
            "description": "Whether the search should ignore letter case. Optional; defaults to False.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of matches to return. Optional; defaults to 200.",
        },
    },
    ["pattern"],
)


find_files_tool = make_tool(
    "find_files",
    "Find files using a glob pattern. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "pattern": {
            "type": "string",
            "description": "Glob pattern such as *.py or **/*.py.",
        },
        "path": {
            "type": "string",
            "description": "Directory to search in. Searches recursively. Optional; defaults to the current directory.",
        },
    },
    ["pattern"],
)


find_symbol_tool = make_tool(
    "find_symbol",
    "Find Python function and class definitions named symbol. Returns a structured result "
    '{"success", "data", "message", "error"}. Matches FUNCTION and CLASS definitions only (kinds: "function", '
    '"async_function", "class"); variables and assignments are NOT matched.',
    {
        "symbol": {
            "type": "string",
            "description": "Symbol name to find.",
        },
        "path": {
            "type": "string",
            "description": "Directory to search in. Searches recursively. Optional; defaults to the current directory.",
        },
    },
    ["symbol"],
)


find_references_tool = make_tool(
    "find_references",
    "Find references to a symbol in the project. Returns a structured result "
    '{"success", "data", "message", "error"}. This is a TEXTUAL word-boundary search, not semantic reference '
    "analysis: it matches comments, strings and the definition itself.",
    {
        "symbol": {
            "type": "string",
            "description": "Symbol name to search for.",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search. Optional; defaults to the current directory.",
        },
    },
    ["symbol"],
)


get_file_symbols_tool = make_tool(
    "get_file_symbols",
    "Return top-level Python classes and functions defined in a file. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to a Python file.",
        }
    },
    ["path"],
)


# ============================================================
# CODE EDITING
# ============================================================

apply_patch_tool = make_tool(
    "apply_patch",
    "Apply a unified diff patch to a file via git apply. Returns a structured result "
    '{"success", "data", "message", "error"}; on success data contains {"file", "changed"}. The patch is validated '
    "with a dry run first and the file is left untouched on failure.",
    {
        "file": {
            "type": "string",
            "description": "Path to the target file.",
        },
        "patch": {
            "type": "string",
            "description": "Unified diff patch describing the changes.",
        },
    },
    ["file", "patch"],
)


insert_text_tool = make_tool(
    "insert_text",
    "Insert text before a specified 1-based line number. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "1-based line number before which to insert.",
        },
        "text": {
            "type": "string",
            "description": "Text to insert.",
        },
    },
    ["path", "line", "text"],
)


replace_text_tool = make_tool(
    "replace_text",
    "Replace occurrences of text inside a file. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "old": {
            "type": "string",
            "description": "Existing text to replace.",
        },
        "new": {
            "type": "string",
            "description": "Replacement text.",
        },
        "count": {
            "type": "integer",
            "description": "Maximum number of replacements. Optional; use -1 for all occurrences.",
        },
    },
    ["path", "old", "new"],
)


delete_lines_tool = make_tool(
    "delete_lines",
    "Delete an inclusive range of lines from a file. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "start_line": {
            "type": "integer",
            "description": "Starting 1-based line number.",
        },
        "end_line": {
            "type": "integer",
            "description": "Ending 1-based line number.",
        },
    },
    ["path", "start_line", "end_line"],
)


# ============================================================
# EXECUTION
# ============================================================

run_command_tool = make_tool(
    "run_command",
    "Execute a shell command. Returns a structured result "
    '{"success", "data", "message", "error"}. Executes an arbitrary shell command and is inherently unsafe - use '
    "only when the command is trusted and necessary.",
    {
        "cmd": {
            "type": "string",
            "description": "Shell command to execute.",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory. Use null for the project root.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds. Optional; defaults to 30.",
        },
    },
    ["cmd"],
)


run_python_tool = make_tool(
    "run_python",
    "Execute a Python file using the current Python interpreter. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "file": {
            "type": "string",
            "description": "Python file to execute.",
        },
        "args": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Optional command-line arguments. Use null for no arguments.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds. Optional; defaults to 30.",
        },
    },
    ["file"],
)


run_tests_tool = make_tool(
    "run_tests",
    "Run the project's test command. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cmd": {
            "type": "string",
            "description": "Test command to run. Optional; defaults to \"pytest\".",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory. Use null for the project root.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds. Optional; defaults to 120.",
        },
    },
    [],
)


check_syntax_tool = make_tool(
    "check_syntax",
    "Check a Python file for syntax errors without executing it. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path to the Python file.",
        }
    },
    ["path"],
)


lint_project_tool = make_tool(
    "lint_project",
    "Run the project's linting command. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cmd": {
            "type": "string",
            "description": "Lint command. Optional; defaults to \"ruff check .\".",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory. Use null for the project root.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds. Optional; defaults to 120.",
        },
    },
    [],
)


typecheck_project_tool = make_tool(
    "typecheck_project",
    "Run the project's type-checking command. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cmd": {
            "type": "string",
            "description": "Type-checking command. Optional; defaults to \"mypy .\".",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory. Use null for the project root.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds. Optional; defaults to 120.",
        },
    },
    [],
)


# ============================================================
# ENVIRONMENT
# ============================================================

get_current_directory_tool = make_tool(
    "get_current_directory",
    "Return the current working directory. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {},
    [],
)


get_project_root_tool = make_tool(
    "get_project_root",
    "Return the root directory of the current Git project. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Path from which to locate the project root. Optional; defaults to the current directory.",
        }
    },
    [],
)


get_environment_tool = make_tool(
    "get_environment",
    "Return safe runtime metadata about the environment. Returns a structured result "
    '{"success", "data", "message", "error"}. Never returns environment variable VALUES (they may contain secrets); '
    "only the directory list of PATH and environment variable NAMES are included.",
    {},
    [],
)


get_python_version_tool = make_tool(
    "get_python_version",
    "Return the currently running Python version. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {},
    [],
)


which_command_tool = make_tool(
    "which_command",
    "Find the executable path for a command. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "command": {
            "type": "string",
            "description": "Command to locate.",
        }
    },
    ["command"],
)


# ============================================================
# PROJECT UNDERSTANDING
# ============================================================

inspect_project_tool = make_tool(
    "inspect_project",
    "Inspect the project's structure and identify important project characteristics. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect. Optional; defaults to the current directory.",
        }
    },
    [],
)


detect_project_type_tool = make_tool(
    "detect_project_type",
    "Detect the likely project types from common configuration files. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect. Optional; defaults to the current directory.",
        }
    },
    [],
)


get_project_metadata_tool = make_tool(
    "get_project_metadata",
    "Extract compact metadata from common project configuration files. Returns a structured result "
    '{"success", "data", "message", "error"}. Only selected fields are extracted; full configuration file contents '
    "are never included.",
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect. Optional; defaults to the current directory.",
        }
    },
    [],
)


# ============================================================
# GIT
# ============================================================

git_status_tool = make_tool(
    "git_status",
    "Return the current Git status. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        }
    },
    [],
)


git_diff_tool = make_tool(
    "git_diff",
    "Show the current unstaged Git diff. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "path": {
            "type": ["string", "null"],
            "description": "Optional file or path to limit the diff. Use null for the whole repository.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    [],
)


git_log_tool = make_tool(
    "git_log",
    "Return recent Git commits. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "n": {
            "type": "integer",
            "description": "Number of commits to return. Optional; defaults to 10.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    [],
)


git_show_tool = make_tool(
    "git_show",
    "Show the contents and metadata of a Git commit. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "commit": {
            "type": "string",
            "description": "Commit identifier. Optional; defaults to HEAD.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    [],
)


git_branch_tool = make_tool(
    "git_branch",
    "List local Git branches. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        }
    },
    [],
)


git_branch_create_tool = make_tool(
    "git_branch_create",
    "Create a new Git branch. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "name": {
            "type": "string",
            "description": "Name of the new branch.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    ["name"],
)


git_branch_switch_tool = make_tool(
    "git_branch_switch",
    "Switch to an existing Git branch. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "name": {
            "type": "string",
            "description": "Branch name to switch to.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    ["name"],
)


git_add_tool = make_tool(
    "git_add",
    "Stage files for the next Git commit. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files or directories to stage.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    ["paths"],
)


git_commit_tool = make_tool(
    "git_commit",
    "Create a Git commit. Returns a structured result "
    '{"success", "data", "message", "error"}. Runs "git commit -m <message>"; does NOT stage changes (run git_add '
    "first) and does not amend or force.",
    {
        "message": {
            "type": "string",
            "description": "Commit message.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        },
    },
    ["message"],
)


git_stash_tool = make_tool(
    "git_stash",
    "Stash current Git changes. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        }
    },
    [],
)


git_stash_pop_tool = make_tool(
    "git_stash_pop",
    "Restore the most recent Git stash. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory. Optional; defaults to the project root.",
        }
    },
    [],
)


# ============================================================
# WEB
# ============================================================

search_web_tool = make_tool(
    "search_web",
    "Search the web for information relevant to the current task. Returns a structured result "
    '{"success", "data", "message", "error"}. Informational: web search is provided natively by the agent\'s Azure '
    "WebSearchTool.",
    {
        "query": {
            "type": "string",
            "description": "Search query.",
        }
    },
    ["query"],
)


fetch_url_tool = make_tool(
    "fetch_url",
    "Fetch text content from a URL. Returns a structured result "
    '{"success", "data", "message", "error"}. The response is limited to ~200KB; truncation is reported in the '
    "result, never silent. Timeouts are honored.",
    {
        "url": {
            "type": "string",
            "description": "URL to fetch.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum request time in seconds. Optional; defaults to 20.",
        },
    },
    ["url"],
)


# ============================================================
# UTILITIES
# ============================================================

get_current_time_tool = make_tool(
    "get_current_time",
    "Return the current local or UTC time. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {
        "utc": {
            "type": "boolean",
            "description": "Whether to return UTC time. Optional; defaults to False (local time).",
        }
    },
    [],
)


calculate_tool = make_tool(
    "calculate",
    "Safely evaluate a mathematical expression. Returns a structured result "
    '{"success", "data", "message", "error"}. Safe arithmetic evaluator (whitelisted math functions only; arbitrary '
    "Python code is NOT executed).",
    {
        "expression": {
            "type": "string",
            "description": "Mathematical expression to calculate.",
        }
    },
    ["expression"],
)


generate_uuid_tool = make_tool(
    "generate_uuid",
    "Generate a random UUID4 identifier. Returns a structured result "
    '{"success", "data", "message", "error"}.',
    {},
    [],
)


# ============================================================
# ALL TOOLS
# ============================================================

ALL_TOOLS = [
    # Filesystem
    list_files_tool,
    list_directory_tree_tool,
    read_file_tool,
    write_file_tool,
    get_file_info_tool,
    create_directory_tool,
    delete_file_tool,
    delete_directory_tool,
    move_file_tool,
    copy_file_tool,

    # Code Search
    search_code_tool,
    grep_tool,
    find_files_tool,
    find_symbol_tool,
    find_references_tool,
    get_file_symbols_tool,

    # Code Editing
    apply_patch_tool,
    insert_text_tool,
    replace_text_tool,
    delete_lines_tool,

    # Execution
    run_command_tool,
    run_python_tool,
    run_tests_tool,
    check_syntax_tool,
    lint_project_tool,
    typecheck_project_tool,

    # Environment
    get_current_directory_tool,
    get_project_root_tool,
    get_environment_tool,
    get_python_version_tool,
    which_command_tool,

    # Project Understanding
    inspect_project_tool,
    detect_project_type_tool,
    get_project_metadata_tool,

    # Git
    git_status_tool,
    git_diff_tool,
    git_log_tool,
    git_show_tool,
    git_branch_tool,
    git_branch_create_tool,
    git_branch_switch_tool,
    git_add_tool,
    git_commit_tool,
    git_stash_tool,
    git_stash_pop_tool,

    # Web
    search_web_tool,
    fetch_url_tool,

    # Utilities
    get_current_time_tool,
    calculate_tool,
    generate_uuid_tool,
]
