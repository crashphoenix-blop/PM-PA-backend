import os
import subprocess
import sys


def run() -> None:
    subprocess.check_call(["alembic", "upgrade", "head"])
    subprocess.check_call([sys.executable, "-m", "scripts.seed_gifts"])

    port = os.getenv("PORT", "8000")
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port],
    )


if __name__ == "__main__":
    run()
