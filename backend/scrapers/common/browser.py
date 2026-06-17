import os
import platform

def get_browser_args():
    """
    Returns a list of production-grade browser arguments for Chromium.
    Ensures stability in Docker/Linux environments and improves anti-detection.
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
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-breakpad",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-hang-monitor",
        "--disable-prompt-on-repost",
        "--disable-client-side-phishing-detection",
        "--safebrowsing-disable-auto-update",
        "--disable-session-crashed-bubble",
        "--disable-ipc-flooding-protection",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=site-per-process,TranslateUI",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--disable-software-rasterizer",
    ]

    # Linux/Docker specific arguments
    # --no-sandbox is REQUIRED for running as root in Docker
    if os.name != 'nt' or os.environ.get("DOCKER_CONTAINER"):
        args.extend([
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ])
    
    # Add any extra flags from environment
    extra_flags = os.environ.get("CHROMIUM_FLAGS", "")
    if extra_flags:
        for flag in extra_flags.split():
            if flag not in args:
                args.append(flag)

    return args
