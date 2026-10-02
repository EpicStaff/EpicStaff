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
    secrets?: DeclaredSecretRef[];
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
