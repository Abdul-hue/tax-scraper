import os
import glob

def restore_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content.replace(
        'headless=False',
        'headless=True'
    ).replace(
        'self.headless = False',
        'self.headless = True'
    )

    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {path}")

for filepath in glob.glob('backend/**/*.py', recursive=True):
    restore_file(filepath)
