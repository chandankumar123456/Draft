from azure.ai.projects.models import FunctionTool

from tools.functions import (
    # Filesystem
    list_files,
    list_directory_tree,
    read_file,
    write_file,
    get_file_info,
    create_directory,
    delete_file,
    delete_directory,
    move_file,
    copy_file,

    # Code Search
    search_code,
    grep,
    find_files,
    find_symbol,
    find_references,
    get_file_symbols,

    # Code Editing
    apply_patch,
    insert_text,
    replace_text,
    delete_lines,

    # Execution
    run_command,
    run_python,
    run_tests,
    check_syntax,
    lint_project,
    typecheck_project,

    # Environment
    get_current_directory,
    get_project_root,
    get_environment,
    get_python_version,
    which_command,

    # Project Understanding
    inspect_project,
    detect_project_type,
    get_project_metadata,

    # Git
    git_status,
    git_diff,
    git_log,
    git_show,
    git_branch,
    git_branch_create,
    git_branch_switch,
    git_add,
    git_commit,
    git_stash,
    git_stash_pop,

    # Web
    search_web,
    fetch_url,

    # Utilities
    get_current_time,
    calculate,
    generate_uuid,
)


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
    "List files and directories inside the given directory.",
    {
        "directory": {
            "type": "string",
            "description": "Directory path to inspect.",
        }
    },
    ["directory"],
)


list_directory_tree_tool = make_tool(
    "list_directory_tree",
    "Return a recursive directory tree up to the specified depth.",
    {
        "path": {
            "type": "string",
            "description": "Directory path to inspect.",
        },
        "depth": {
            "type": "integer",
            "description": "Maximum recursion depth.",
        },
    },
    ["path", "depth"],
)


read_file_tool = make_tool(
    "read_file",
    "Read the contents of a text file, optionally restricting the returned line range.",
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "start_line": {
            "type": ["integer", "null"],
            "description": "1-based starting line. Use null to start from the beginning.",
        },
        "end_line": {
            "type": ["integer", "null"],
            "description": "1-based ending line. Use null to read until the end.",
        },
    },
    ["path", "start_line", "end_line"],
)


write_file_tool = make_tool(
    "write_file",
    "Write text content to a file.",
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
            "description": "Whether an existing file may be overwritten.",
        },
    },
    ["path", "content", "overwrite"],
)


get_file_info_tool = make_tool(
    "get_file_info",
    "Return metadata about a file or directory.",
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
    "Create a directory and any missing parent directories.",
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
    "Delete a file.",
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
    "Delete a directory.",
    {
        "path": {
            "type": "string",
            "description": "Directory path to delete.",
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to recursively delete the directory contents.",
        },
    },
    ["path", "recursive"],
)


move_file_tool = make_tool(
    "move_file",
    "Move a file or directory to another location.",
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
    "Copy a file or directory to another location.",
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
    "Search source code files for a text query.",
    {
        "query": {
            "type": "string",
            "description": "Text to search for.",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search.",
        },
        "extensions": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Optional list of file extensions to include.",
        },
    },
    ["query", "path", "extensions"],
)


grep_tool = make_tool(
    "grep",
    "Search files using a regular expression pattern.",
    {
        "pattern": {
            "type": "string",
            "description": "Regular expression pattern.",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search.",
        },
        "ignore_case": {
            "type": "boolean",
            "description": "Whether the search should ignore letter case.",
        },
    },
    ["pattern", "path", "ignore_case"],
)


find_files_tool = make_tool(
    "find_files",
    "Find files using a glob pattern.",
    {
        "pattern": {
            "type": "string",
            "description": "Glob pattern such as *.py or **/*.py.",
        },
        "path": {
            "type": "string",
            "description": "Root directory to search.",
        },
    },
    ["pattern", "path"],
)


find_symbol_tool = make_tool(
    "find_symbol",
    "Find Python classes, functions, or other named symbols in a project.",
    {
        "symbol": {
            "type": "string",
            "description": "Symbol name to find.",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search.",
        },
    },
    ["symbol", "path"],
)


find_references_tool = make_tool(
    "find_references",
    "Find references to a symbol in the project.",
    {
        "symbol": {
            "type": "string",
            "description": "Symbol name to search for.",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search.",
        },
    },
    ["symbol", "path"],
)


get_file_symbols_tool = make_tool(
    "get_file_symbols",
    "Return top-level Python classes and functions defined in a file.",
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
    "Apply a unified diff patch to a file.",
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
    "Insert text before a specified 1-based line number.",
    {
        "path": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "1-based line number.",
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
    "Replace occurrences of text inside a file.",
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
            "description": "Maximum number of replacements. Use -1 for all occurrences.",
        },
    },
    ["path", "old", "new", "count"],
)


delete_lines_tool = make_tool(
    "delete_lines",
    "Delete an inclusive range of lines from a file.",
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
    "Execute a shell command.",
    {
        "cmd": {
            "type": "string",
            "description": "Shell command to execute.",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory. Use null for the current directory.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds.",
        },
    },
    ["cmd", "cwd", "timeout"],
)


run_python_tool = make_tool(
    "run_python",
    "Execute a Python file using the current Python interpreter.",
    {
        "file": {
            "type": "string",
            "description": "Python file to execute.",
        },
        "args": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Optional command-line arguments.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds.",
        },
    },
    ["file", "args", "timeout"],
)


run_tests_tool = make_tool(
    "run_tests",
    "Run the project's test command.",
    {
        "cmd": {
            "type": "string",
            "description": "Test command to run, such as pytest.",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds.",
        },
    },
    ["cmd", "cwd", "timeout"],
)


check_syntax_tool = make_tool(
    "check_syntax",
    "Check a Python file for syntax errors without executing it.",
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
    "Run the project's linting command.",
    {
        "cmd": {
            "type": "string",
            "description": "Lint command, such as ruff check .",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds.",
        },
    },
    ["cmd", "cwd", "timeout"],
)


typecheck_project_tool = make_tool(
    "typecheck_project",
    "Run the project's type-checking command.",
    {
        "cmd": {
            "type": "string",
            "description": "Type-checking command, such as mypy .",
        },
        "cwd": {
            "type": ["string", "null"],
            "description": "Working directory.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds.",
        },
    },
    ["cmd", "cwd", "timeout"],
)


# ============================================================
# ENVIRONMENT
# ============================================================

get_current_directory_tool = make_tool(
    "get_current_directory",
    "Return the current working directory.",
    {},
    [],
)


get_project_root_tool = make_tool(
    "get_project_root",
    "Return the root directory of the current Git project.",
    {
        "path": {
            "type": "string",
            "description": "Path from which to locate the project root.",
        }
    },
    ["path"],
)


get_environment_tool = make_tool(
    "get_environment",
    "Return the current environment variables.",
    {},
    [],
)


get_python_version_tool = make_tool(
    "get_python_version",
    "Return the currently running Python version.",
    {},
    [],
)


which_command_tool = make_tool(
    "which_command",
    "Find the executable path for a command.",
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
    "Inspect the project's structure and identify important project characteristics.",
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect.",
        }
    },
    ["path"],
)


detect_project_type_tool = make_tool(
    "detect_project_type",
    "Detect the likely project types from common configuration files.",
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect.",
        }
    },
    ["path"],
)


get_project_metadata_tool = make_tool(
    "get_project_metadata",
    "Read common project configuration and metadata.",
    {
        "path": {
            "type": "string",
            "description": "Project directory to inspect.",
        }
    },
    ["path"],
)


# ============================================================
# GIT
# ============================================================

git_status_tool = make_tool(
    "git_status",
    "Return the current Git status.",
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        }
    },
    ["cwd"],
)


git_diff_tool = make_tool(
    "git_diff",
    "Show the current unstaged Git diff.",
    {
        "path": {
            "type": ["string", "null"],
            "description": "Optional file or path to limit the diff.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["path", "cwd"],
)


git_log_tool = make_tool(
    "git_log",
    "Return recent Git commits.",
    {
        "n": {
            "type": "integer",
            "description": "Number of commits to return.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["n", "cwd"],
)


git_show_tool = make_tool(
    "git_show",
    "Show the contents and metadata of a Git commit.",
    {
        "commit": {
            "type": "string",
            "description": "Commit identifier, such as HEAD or a commit SHA.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["commit", "cwd"],
)


git_branch_tool = make_tool(
    "git_branch",
    "List local Git branches.",
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        }
    },
    ["cwd"],
)


git_branch_create_tool = make_tool(
    "git_branch_create",
    "Create a new Git branch.",
    {
        "name": {
            "type": "string",
            "description": "Name of the new branch.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["name", "cwd"],
)


git_branch_switch_tool = make_tool(
    "git_branch_switch",
    "Switch to an existing Git branch.",
    {
        "name": {
            "type": "string",
            "description": "Branch name to switch to.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["name", "cwd"],
)


git_add_tool = make_tool(
    "git_add",
    "Stage files for the next Git commit.",
    {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files or directories to stage.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["paths", "cwd"],
)


git_commit_tool = make_tool(
    "git_commit",
    "Create a Git commit.",
    {
        "message": {
            "type": "string",
            "description": "Commit message.",
        },
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        },
    },
    ["message", "cwd"],
)


git_stash_tool = make_tool(
    "git_stash",
    "Stash current Git changes.",
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        }
    },
    ["cwd"],
)


git_stash_pop_tool = make_tool(
    "git_stash_pop",
    "Restore the most recent Git stash.",
    {
        "cwd": {
            "type": "string",
            "description": "Git repository directory.",
        }
    },
    ["cwd"],
)


# ============================================================
# WEB
# ============================================================

search_web_tool = make_tool(
    "search_web",
    "Search the web for information relevant to the current task.",
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
    "Fetch text content from a URL.",
    {
        "url": {
            "type": "string",
            "description": "URL to fetch.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum request time in seconds.",
        },
    },
    ["url", "timeout"],
)


# ============================================================
# UTILITIES
# ============================================================

get_current_time_tool = make_tool(
    "get_current_time",
    "Return the current local or UTC time.",
    {
        "utc": {
            "type": "boolean",
            "description": "Whether to return UTC time.",
        }
    },
    ["utc"],
)


calculate_tool = make_tool(
    "calculate",
    "Safely evaluate a mathematical expression.",
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
    "Generate a random UUID4 identifier.",
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