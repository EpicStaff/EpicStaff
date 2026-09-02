export interface GetPythonCodeRequest {
    id: number;
    libraries: string[];
    code: string;
    entrypoint: string;
    secret_ids?: number[];
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
}
