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
        "--disable-infobars",
        "--disable-popup-blocking",
        "--disable-extensions",
        "--disable-notifications",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process,VizDisplayCompositor",
    ]

    # Linux/Docker specific arguments
    # --no-sandbox is REQUIRED for running as root in Docker
    if os.name != 'nt' or os.environ.get("DOCKER_CONTAINER"):
        args.extend([
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
        ])
    
    # Add any extra flags from environment
    extra_flags = os.environ.get("CHROMIUM_FLAGS", "")
    if extra_flags:
        for flag in extra_flags.split():
            if flag not in args:
                args.append(flag)

    return args
