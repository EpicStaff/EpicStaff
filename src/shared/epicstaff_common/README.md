# epicstaff_common

Shared helper code for sandbox Python tools (`src/shared/tools/*/main.py`).

Each tool ships as a standalone `main.py` uploaded to the sandbox — tools
can't import from the repo directly. This package is installed into every
tool's venv unconditionally (see `predefined_libraries` in
`src/sandbox/dynamic_venv_executor_chain.py`), so shared code placed here is
available to import in any tool without duplicating it per tool.

Unlike `dotdict`, imports from this package are **not** auto-injected. Each
tool must write a real, explicit import statement, the same way tools already
import `epicstaff_storage`:

```python
from epicstaff_common import something
```

An explicit import is IDE-resolvable — auto-injected names (like `dotdict`)
show up as undefined to editors/linters.

Adding or changing code here requires no per-tool changes: the package is
already installed into every sandbox venv; tools opt in by importing what
they need.

