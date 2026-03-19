import json
from main import main


def ask_param(prompt, default=None):
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def run_test():
    params = {
        "search_query": ask_param("Enter SQL search query"),
        "host": ask_param("Database host"),
        "user": ask_param("Database user"),
        "password": ask_param("Database password"),
        "port": int(ask_param("Database port", "3306")),
        "database": ask_param("Database name"),
        "ssl_key": ask_param("SSL key path", None),
        "ssl_cert": ask_param("SSL cert path", None),
        "ssl_ca": ask_param("SSL CA path", None),
        "tables": ask_param("Tables (comma separated)", "").split(",")
        if ask_param("Tables (comma separated)", "")
        else [],
    }

    result = main(**params)
    print("=== Search Result ===")
    print(result)


if __name__ == "__main__":
    run_test()
