import os
import platform

def get_browser_args():
    """
    Returns a list of production-grade browser arguments for Chromium.
    Ensures stability in Docker/Linux environments.
    """
    # Base arguments for all environments
    args = [
        "--disable-blink-features=AutomationControlled",
    ]

    # Linux/Docker specific arguments
    if platform.system() == "Linux" or os.environ.get("DOCKER_CONTAINER"):
        args.extend([
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
            "--single-process",
        ])
    
    # Add any extra flags from environment
    extra_flags = os.environ.get("CHROMIUM_FLAGS", "")
    if extra_flags:
        for flag in extra_flags.split():
            if flag not in args:
                args.append(flag)

    return args
