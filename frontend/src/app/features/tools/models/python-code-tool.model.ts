import { CreatePythonCodeRequest, GetPythonCodeRequest, UpdatePythonCodeRequest } from './python-code.model';

export interface ArgsSchema {
    $schema?: string;
    title: string;
    type: string;
    properties: {
        [key: string]: {
            type: string;
            description?: string;
            required?: boolean;
        };
    };
    required?: string[];
}

export interface GetPythonCodeToolRequest {
    id: number;
    python_code: GetPythonCodeRequest;
    name: string;
    description: string;
    args_schema: ArgsSchema;
    built_in: boolean;
    variables?: unknown[];
    use_storage?: boolean;
}
export interface CreatePythonCodeToolRequest {
    python_code: CreatePythonCodeRequest;
    name: string;
    description: string;
    args_schema: ArgsSchema;
    use_storage?: boolean;
}

export interface UpdatePythonCodeToolRequest {
    id: number;
    python_code: UpdatePythonCodeRequest;
    name: string; // Required, minLength: 1
    description: string;
    args_schema: ArgsSchema; // Now an object rather than a JSON string
    use_storage?: boolean;    
}

/**
 * Nested `python_code` body accepted by the V2 Python Code Tool create
 * endpoint. Mirrors the Django `PythonCodeSerializer` (libraries as string[],
 * entrypoint defaulting to "main", and free-form `global_kwargs`).
 */
export interface CreatePythonCodeBody {
    code: string;
    entrypoint: string;
    libraries: string[];
    global_kwargs: Record<string, unknown>;
}

/**
 * V2 payload for `POST /api/python-code-tool/`.
 *
 * The backend dropped `args_schema` in favor of a free-form `variables` JSON
 * list; see migration `0170_pythoncodetool_variables_drop_args_schema.py`.
 * The legacy {@link CreatePythonCodeToolRequest} type is preserved so the
 * existing `CustomToolDialogComponent` keeps compiling until it is retired.
 */
export interface CreatePythonCodeToolPayload {
    name: string;
    description: string;
    variables: unknown[];
    python_code: CreatePythonCodeBody;
}

/**
 * Nested `python_code` body accepted by the V2 Python Code Tool create
 * endpoint. Mirrors the Django `PythonCodeSerializer` (libraries as string[],
 * entrypoint defaulting to "main", and free-form `global_kwargs`).
 */
export interface CreatePythonCodeBody {
    code: string;
    entrypoint: string;
    libraries: string[];
    global_kwargs: Record<string, unknown>;
}

/**
 * V2 payload for `POST /api/python-code-tool/`.
 *
 * The backend dropped `args_schema` in favor of a free-form `variables` JSON
 * list; see migration `0170_pythoncodetool_variables_drop_args_schema.py`.
 * The legacy {@link CreatePythonCodeToolRequest} type is preserved so the
 * existing `CustomToolDialogComponent` keeps compiling until it is retired.
 */
export interface CreatePythonCodeToolPayload {
    name: string;
    description: string;
    variables: unknown[];
    python_code: CreatePythonCodeBody;
}
