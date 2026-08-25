import { NodeModel } from '../../core/models/node.model';
import { mapAudioToTextNodeToModel } from './nodes/audio-to-text-node.mapper';
import { mapClassificationDecisionTableNodeToModel } from './nodes/classification-decision-table-node.mapper';
import { mapCodeAgentNodeToModel } from './nodes/code-agent-node.mapper';
import { mapCrewNodeToModel } from './nodes/crew-node.mapper';
import { mapDecisionTableNodeToModel } from './nodes/decision-table-node.mapper';
import { mapEndNodeToModel } from './nodes/end-node.mapper';
import { mapFileExtractorNodeToModel } from './nodes/file-extractor-node.mapper';
import { mapGraphNoteToModel } from './nodes/graph-note.mapper';
import { mapLLMNodeToModel } from './nodes/llm-node.mapper';
import { mapPythonNodeToModel } from './nodes/python-node.mapper';
import { mapScheduleTriggerNodeToModel } from './nodes/schedule-trigger-node.mapper';
import { mapStartNodeToModel } from './nodes/start-node.mapper';
import { mapSubGraphNodeToModel } from './nodes/subgraph-node.mapper';
import { mapTelegramTriggerNodeToModel } from './nodes/telegram-trigger-node.mapper';
import { mapWebhookTriggerNodeToModel } from './nodes/webhook-trigger-node.mapper';

/**
 * Converts a WS node payload (bulk-save format) to a canvas NodeModel by
 * reusing the same per-type mappers used during graph load.
 *
 * For temp nodes (not yet persisted): canvas id = temp_id, backendId = null.
 * For persisted nodes: canvas id = stableNodeId(type, id), backendId = id.
 *
 * Returns null for unknown list_key values (e.g. edge lists).
 */
export function mapWsNodePayloadToModel(payload: Record<string, unknown>, listKey: string): NodeModel | null {
    const tempId = typeof payload['temp_id'] === 'string' ? payload['temp_id'] : undefined;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const dto: any = { ...payload, id: typeof payload['id'] === 'number' ? payload['id'] : 0 };

    let model: NodeModel | null = null;
    switch (listKey) {
        case 'start_node_list':
            model = mapStartNodeToModel(dto);
            break;
        case 'end_node_list':
            model = mapEndNodeToModel(dto);
            break;
        case 'python_node_list':
            model = mapPythonNodeToModel(dto);
            break;
        case 'crew_node_list':
            model = mapCrewNodeToModel(dto);
            break;
        case 'file_extractor_node_list':
            model = mapFileExtractorNodeToModel(dto);
            break;
        case 'audio_transcription_node_list':
            model = mapAudioToTextNodeToModel(dto);
            break;
        case 'subgraph_node_list':
            model = mapSubGraphNodeToModel(dto);
            break;
        case 'graph_note_list':
            model = mapGraphNoteToModel(dto);
            break;
        case 'webhook_trigger_node_list':
            model = mapWebhookTriggerNodeToModel(dto);
            break;
        case 'telegram_trigger_node_list':
            model = mapTelegramTriggerNodeToModel(dto);
            break;
        case 'schedule_trigger_node_list':
            model = mapScheduleTriggerNodeToModel(dto);
            break;
        case 'code_agent_node_list':
            model = mapCodeAgentNodeToModel(dto);
            break;
        case 'decision_table_node_list':
            model = mapDecisionTableNodeToModel(dto);
            break;
        case 'classification_decision_table_node_list':
            model = mapClassificationDecisionTableNodeToModel(dto);
            break;
        case 'llm_node_list':
            model = mapLLMNodeToModel(dto);
            break;
        default:
            return null;
    }

    if (!model) return null;

    if (tempId) {
        return { ...model, id: tempId, backendId: null };
    }
    return model;
}
