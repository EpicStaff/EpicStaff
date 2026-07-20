import { GetPythonCodeRequest } from '../../../../../features/tools/models/python-code.model';
import { WebhookTriggerModel } from '../../../../../visual-programming/core/models/webhook-trigger.model';

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
