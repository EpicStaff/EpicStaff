import { CreatePythonCodeToolPayload } from '../../../../../features/tools/models/python-code-tool.model';

export interface CreateCustomToolFormValue {
    name: string;
    description: string;
    pythonCode: string;
    variablesJson: string;
    libraries: string[];
    useStorage: boolean;
}

export const DEFAULT_ENTRYPOINT = 'main';

export interface PreservedToolFields {
    entrypoint?: string;
}

/**
 * Map the dialog's reactive form value into the request payload accepted by
 * `POST /api/python-code-tool/`.
 *
 * Throws if `variablesJson` is not valid JSON. Caller should guard with the
 * editor's own validity flag before invoking.
 */
export function toCreatePayload(
    form: CreateCustomToolFormValue,
    secretIds: number[],
    preserved: PreservedToolFields = {}
): CreatePythonCodeToolPayload {
    const parsedVariables = JSON.parse(form.variablesJson) as unknown;

    return {
        name: form.name.trim(),
        description: form.description.trim(),
        variables: Array.isArray(parsedVariables) ? parsedVariables : [],
        python_code: {
            code: form.pythonCode,
            entrypoint: preserved.entrypoint?.trim() || DEFAULT_ENTRYPOINT,
            libraries: form.libraries,
            global_kwargs: {},
            secret_ids: secretIds,
        },
        // The `useStorage` form control is the source of truth for new edits; it is seeded
        // from `selectedTool()?.use_storage ?? false`, so an existing tool's value is still
        // preserved whenever the user doesn't touch the toggle.
        use_storage: form.useStorage,
    };
}
