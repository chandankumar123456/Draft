# this is a file for Draft mainly it consists of all tools
from pathlib import Path

def list_files(directory: str = ".") -> list[str]:
    """
    List files and directories inside the given directory.

    Args:
        directory: Directory path to inspect. Defaults to the current directory.

    Returns:
        A list containing the paths of files and directories.
    """
    path = Path(directory)
    
    if not path.exists():
        return [f"Error: directory does not exist: {directory}"]
    
    if not path.is_dir():
        return [f"Error: path is not a directory: {directory}"]
    return [str(item) for item in path.iterdir()]


# print(list_files())