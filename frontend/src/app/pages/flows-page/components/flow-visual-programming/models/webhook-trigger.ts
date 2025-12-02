import { CreatePythonCodeRequest, GetPythonCodeRequest } from "../../../../../features/tools/models/python-code.model";

export interface GetWebhookTriggerNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
}

export interface CreateWebhookTriggerNodeRequest {
    node_name: string;
    graph: number;
    python_code: CreatePythonCodeRequest;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
}
