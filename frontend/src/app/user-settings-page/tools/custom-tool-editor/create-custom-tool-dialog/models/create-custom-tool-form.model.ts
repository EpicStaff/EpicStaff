import { CreatePythonCodeToolPayload } from '../../../../../features/tools/models/python-code-tool.model';

export interface CreateCustomToolFormValue {
    name: string;
    description: string;
    pythonCode: string;
    variablesJson: string;
    libraries: string[];
}

/**
 * Map the dialog's reactive form value into the request payload accepted by
 * `POST /api/python-code-tool/`.
 *
 * Throws if `variablesJson` is not valid JSON. Caller should guard with the
 * editor's own validity flag before invoking.
 */
export function toCreatePayload(form: CreateCustomToolFormValue): CreatePythonCodeToolPayload {
    const parsedVariables = JSON.parse(form.variablesJson) as unknown;

    return {
        name: form.name.trim(),
        description: form.description.trim(),
        variables: Array.isArray(parsedVariables) ? parsedVariables : [],
        python_code: {
            code: form.pythonCode,
            entrypoint: 'main',
            libraries: form.libraries,
            global_kwargs: {},
        },
    };
}
