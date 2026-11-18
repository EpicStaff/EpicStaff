export const SECRET_CODE_NEEDS_USE_MESSAGE =
    'This code reads secrets. Editing it requires the Use permission on Secrets.';

export const SECRET_CODE_COPY_NEEDS_USE_MESSAGE =
    'This code reads secrets. Copying it requires the Use permission on Secrets.';

/**
 * Without Secrets:Use the backend refuses changing Python code that reads secrets (its code, entrypoint, venv,
 * global kwargs) and copying it: the secrets are handed to that code at run time. Whatever holds the code (a
 * tool, a flow node) keeps its other fields editable.
 */
export function isSecretCodeLocked(secretIds: readonly number[], canUseSecrets: boolean): boolean {
    return !canUseSecrets && secretIds.length > 0;
}
