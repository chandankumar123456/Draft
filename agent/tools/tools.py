from azure.ai.projects.models import FunctionTool
from tools.functions import list_files

list_files_tool = FunctionTool(
    name="list_files",
    description="List files and directories inside the given directory.",
    parameters={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory Path to inspect"
            }
        },
        "required": ["directory"],
        "additionalProperties": False
    },
    strict=True
)