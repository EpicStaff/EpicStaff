"""Executable file extensions the storage library refuses to write.

A copy of django_app's `FileValidator.BLOCKED_EXTENSIONS`: this library runs inside the
sandbox and can't import django_app. A django test asserts the two stay equal, so change
both together.
"""

BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Windows executables & installers
        ".exe",
        ".msi",
        ".com",
        ".scr",
        ".pif",
        # Windows scripting
        ".bat",
        ".cmd",
        ".vbs",
        ".vbe",
        ".wsh",
        ".wsf",
        ".ps1",
        ".psm1",
        ".psd1",
        # Unix/macOS executables
        ".sh",
        ".bash",
        ".csh",
        ".ksh",
        ".zsh",
        ".app",
        ".command",
        ".elf",
        # Java archives (executable)
        ".jar",
        ".war",
        ".ear",
        # Shared libraries
        ".dll",
        ".so",
        ".dylib",
    }
)
