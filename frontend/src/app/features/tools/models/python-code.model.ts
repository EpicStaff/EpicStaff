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
    name: string;
    libraries: string[];
    code: string;
    entrypoint: string;
}
