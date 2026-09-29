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
    libraries: string[];
    code: string;
    entrypoint: string;
    /** REST read shape: declared secrets with names (permission-filtered by the backend). */
    secrets?: DeclaredSecretRef[];
    /** Write shape; also what live-collaboration (WS) payloads carry. */
    secret_ids?: number[];
    /** Present only on WS payloads that were built from the FE model. */
    secret_names?: string[];
}

export interface CreatePythonCodeRequest {
    libraries: string[];
    code: string;
    entrypoint: string;
}

export interface UpdatePythonCodeRequest {
    id: number;
    libraries: string[];
    code: string;
    entrypoint: string;
}

//used when creating python code node
export interface CustomPythonCode {
    id?: number | null;
    name: string;
    libraries: string[];
    code: string;
    entrypoint: string;
    use_storage?: boolean;
    secret_ids?: number[];
    secret_names?: string[];
}
