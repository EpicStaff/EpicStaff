export interface DeclaredSecretRef {
    id: number;
    name: string;
}

export function toSecretIds(secrets: DeclaredSecretRef[] | undefined): number[] {
    return (secrets ?? []).map((secret) => secret.id);
}

export function toSecretNames(secrets: DeclaredSecretRef[] | undefined): string[] {
    return (secrets ?? []).map((secret) => secret.name);
}

export interface GetPythonCodeRequest {
    id: number;
    code: string;
    entrypoint: string;
    venv_id?: number | null;
    global_kwargs?: Record<string, unknown>;
    secrets?: DeclaredSecretRef[];
    /** Seconds one run of the code may take. Absent in flow versions saved before code had a timeout. */
    execution_timeout?: number;
}

export interface CreatePythonCodeRequest {
    code: string;
    entrypoint: string;
}

export interface UpdatePythonCodeRequest {
    id: number;
    code: string;
    entrypoint: string;
}

//used when creating python code node
export interface CustomPythonCode {
    id?: number | null;
    name: string;
    code: string;
    entrypoint: string;
    use_storage?: boolean;
    secret_ids?: number[];
    secret_names?: string[];
    venv_id?: number | null;
    /** Stored with the code; absent for new code. Sent back as loaded: the panels do not edit it. */
    global_kwargs?: Record<string, unknown>;
    /** Seconds one run of the code may take; absent until set, then the backend applies its default. */
    execution_timeout?: number;
}
