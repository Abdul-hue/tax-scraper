import os
import glob

def clean_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content.replace(
        'self.headless = os.getenv("HEADLESS", "true").lower() == "true"',
        'self.headless = False'
    ).replace(
        'headless=True',
        'headless=False'
    ).replace(
        'headless=getattr(self, "headless", True)',
        'headless=self.headless'
    ).replace(
        'os.getenv("HEADLESS", "true").lower() == "true"',
        'False'
    )

    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {path}")

for filepath in glob.glob('backend/**/*.py', recursive=True):
    clean_file(filepath)
