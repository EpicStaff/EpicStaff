import { AuthorshipFields, CreatePythonCodeRequest, GetPythonCodeRequest } from '@shared/models';

export interface GetWebhookTriggerNodeRequest extends AuthorshipFields {
    id: number;
    node_name: string;
    graph: number;
    python_code: GetPythonCodeRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
    metadata: Record<string, unknown>;
    /** Id of the referenced webhook trigger — the graph API and the version snapshot both send a bare id. */
    webhook_trigger: number | null;
}

export interface CreateWebhookTriggerNodeRequest {
    node_name: string;
    graph: number;
    python_code: CreatePythonCodeRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    webhook_trigger_path: string;
    metadata?: Record<string, unknown>;
    /** Bulk save accepts only the id of an existing trigger; triggers are created through `/webhook-triggers/`. */
    webhook_trigger: number | null;
}
