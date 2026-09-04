# Cli Tool
import subprocess


def main(command: str) -> str:
    """
    Execute a CLI command and return its stdout and stderr.

    Args:
        command (str): The command to run.

    Returns:
        str: stdout and stderr.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        result = f"STDOUT: \n{result.stdout}\nSTDERR: \n{result.stderr}"
        return result
    except Exception as e:
        return "", str(e)
