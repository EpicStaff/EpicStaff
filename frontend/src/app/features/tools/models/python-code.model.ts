export interface GetPythonCodeRequest {
    id: number;
    libraries: string[];
    code: string;
    entrypoint: string;
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
    // TODO: PythonNode has no secrets relation on the backend yet (unlike LLMConfig's
    // api_key_secret). This is stored here so the UI has somewhere to hold the selection,
    // but the backend currently has no field to receive it — it won't actually persist.
    secret_ids?: number[];
}
