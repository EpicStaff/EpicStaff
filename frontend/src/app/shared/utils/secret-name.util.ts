/**
 * The characters a secret name may use: Unicode letters and digits, space, `_`, `-` and `.`.
 * Identical to the server's rule (Python `str.isalnum()` or one of ` _-.`). An allowlist, because the code-editor
 * autocomplete inserts the name into Python code as `get_secret("name")` — also inside strings, including f-strings,
 * where characters such as `{ }` or quotes would run as code.
 */
const SECRET_NAME_PATTERN = /^[\p{L}\p{N} _.-]+$/u;

export function isAllowedSecretName(name: string): boolean {
    return SECRET_NAME_PATTERN.test(name);
}
