import { GetProjectRequest } from '../../../../../features/projects/models/project.model';

export interface CrewNode {
    id: number;
    node_name: string;
    graph: number;
    crew: GetProjectRequest;
    input_map: Record<string, unknown>;
    output_variable_path: string | null;
    stream_config?: Record<string, boolean>;
    metadata: Record<string, unknown>;
}
