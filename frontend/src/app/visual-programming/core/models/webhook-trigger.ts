import {
    CreatePythonCodeRequest,
    GetPythonCodeRequest,
    WebhookTriggerModel,
    WebhookTriggerWrite,
} from '@shared/models';

export interface GetWebhookTriggerNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
    metadata: Record<string, unknown>;
    webhook_trigger: WebhookTriggerModel | null;
}

export interface CreateWebhookTriggerNodeRequest {
    node_name: string;
    graph: number;
    python_code: CreatePythonCodeRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
    metadata?: Record<string, unknown>;
    webhook_trigger: WebhookTriggerWrite | null;
}
