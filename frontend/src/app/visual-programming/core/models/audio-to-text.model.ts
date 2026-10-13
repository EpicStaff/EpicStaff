import { AuthorshipFields } from '@shared/models';

export interface GetAudioToTextNodeRequest extends AuthorshipFields {
    id: number;
    created_at: string;
    node_name: string;
    graph: number;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    metadata: Record<string, unknown>;
    /**
     * Minutes one sandbox execution of the node's code may run (1 to the sandbox ceiling). The API always sends
     * it; a version snapshot saved before nodes had a timeout does not.
     */
    execution_timeout?: number;
}
