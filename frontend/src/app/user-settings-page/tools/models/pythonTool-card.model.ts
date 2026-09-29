import { ArgsSchema, GetPythonCodeRequest } from '@shared/models';
export interface PythonCodeToolCard {
    id: number;
    python_code: GetPythonCodeRequest;
    name: string; // Required, minLength: 1
    description: string;
    args_schema: ArgsSchema; // Now an object rather than a JSON string
}
