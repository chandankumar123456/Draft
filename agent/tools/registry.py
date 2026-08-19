from tools.functions import (
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

    search_code,
    grep,
    find_files,
    find_symbol,
    find_references,
    get_file_symbols,

    apply_patch,
    insert_text,
    replace_text,
    delete_lines,

    run_command,
    run_python,
    run_tests,
    check_syntax,
    lint_project,
    typecheck_project,

    get_current_directory,
    get_project_root,
    get_environment,
    get_python_version,
    which_command,

    inspect_project,
    detect_project_type,
    get_project_metadata,

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

    search_web,
    fetch_url,

    get_current_time,
    calculate,
    generate_uuid,
)

from subagents import spawn_subagent


TOOL_REGISTRY = {
    "list_files": list_files,
    "list_directory_tree": list_directory_tree,
    "read_file": read_file,
    "write_file": write_file,
    "get_file_info": get_file_info,
    "create_directory": create_directory,
    "delete_file": delete_file,
    "delete_directory": delete_directory,
    "move_file": move_file,
    "copy_file": copy_file,

    "search_code": search_code,
    "grep": grep,
    "find_files": find_files,
    "find_symbol": find_symbol,
    "find_references": find_references,
    "get_file_symbols": get_file_symbols,

    "apply_patch": apply_patch,
    "insert_text": insert_text,
    "replace_text": replace_text,
    "delete_lines": delete_lines,

    "run_command": run_command,
    "run_python": run_python,
    "run_tests": run_tests,
    "check_syntax": check_syntax,
    "lint_project": lint_project,
    "typecheck_project": typecheck_project,

    "get_current_directory": get_current_directory,
    "get_project_root": get_project_root,
    "get_environment": get_environment,
    "get_python_version": get_python_version,
    "which_command": which_command,

    "inspect_project": inspect_project,
    "detect_project_type": detect_project_type,
    "get_project_metadata": get_project_metadata,

    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
    "git_show": git_show,
    "git_branch": git_branch,
    "git_branch_create": git_branch_create,
    "git_branch_switch": git_branch_switch,
    "git_add": git_add,
    "git_commit": git_commit,
    "git_stash": git_stash,
    "git_stash_pop": git_stash_pop,

    "search_web": search_web,
    "fetch_url": fetch_url,

    "get_current_time": get_current_time,
    "calculate": calculate,
    "generate_uuid": generate_uuid,

    "spawn_subagent": spawn_subagent,
}