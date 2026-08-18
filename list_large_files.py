import os
from pathlib import Path

def get_largest_files(directory, top_n=10, max_depth=2):
    entries = []
    base_path = Path(directory)
    for root, dirs, files in os.walk(directory):
        # limit depth
        if len(Path(root).relative_to(base_path).parts) > max_depth:
            continue
        for file in files:
            filepath = Path(root) / file
            try:
                size = filepath.stat().st_size
                entries.append((size, str(filepath)))
            except Exception:
                continue
    entries.sort(reverse=True, key=lambda x: x[0])
    return entries[:top_n]

if __name__ == '__main__':
    largest_files = get_largest_files('.', 10, 2)
    for size, filepath in largest_files:
        print(f'{size} bytes - {filepath}')
