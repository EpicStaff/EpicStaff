import { BasePort } from '../models/port.model';
import { DEFAULT_TASK_NODE_PORTS } from './task-ports/task-node-defaults-ports';
import { DEFAULT_LLM_NODE_PORTS } from './llm-ports/llm-node-default-ports';
import { DEFAULT_TOOL_NODE_PORTS } from './tool-ports/tool-node-default-ports';
import { DEFAULT_PROJECT_NODE_PORTS } from './project-ports/project-node-default-ports';
import { DEFAULT_PYTHON_NODE_PORTS } from './python-ports/python-node-default-ports';
import { DEFAULT_EDGE_NODE_PORTS } from './edge-ports/edge-node-default-ports';
import { DEFAULT_START_NODE_PORTS } from './start-ports/start-node-default-ports';
import { DEFAULT_TABLE_NODE_PORTS } from './table-ports/table-ports';
import { DEFAULT_FILE_EXTRACTOR_NODE_PORTS } from './file-extractor-ports/file-extractor-default-ports';
import { DEFAULT_END_NODE_PORTS } from './end-ports/end-ports-default-ports';
import { DEFAULT_SUBGRAPH_NODE_PORTS } from './subgraph-ports/subgraph-node-default-ports';
import { DEFAULT_AUDIO_TO_TEXT_NODE_PORTS } from './audio-to-text-node-ports/audio-to-text-node-ports';
import { DEFAULT_WEBHOOK_TRIGGER_NODE_PORTS } from './webhook-trigger-ports/webhook-trigger-default-ports';

export const PORTS_DICTIONARY: { [role: string]: BasePort } =
    Object.fromEntries(
        [
            ...DEFAULT_TASK_NODE_PORTS,
          
            ...DEFAULT_LLM_NODE_PORTS,
            ...DEFAULT_TOOL_NODE_PORTS,
            ...DEFAULT_PROJECT_NODE_PORTS,
            ...DEFAULT_PYTHON_NODE_PORTS,
            ...DEFAULT_EDGE_NODE_PORTS,
            ...DEFAULT_START_NODE_PORTS,
            ...DEFAULT_TABLE_NODE_PORTS,
            ...DEFAULT_FILE_EXTRACTOR_NODE_PORTS,
            ...DEFAULT_WEBHOOK_TRIGGER_NODE_PORTS,
            ...DEFAULT_END_NODE_PORTS,
            ...DEFAULT_SUBGRAPH_NODE_PORTS,
            ...DEFAULT_AUDIO_TO_TEXT_NODE_PORTS,
        ].map((port) => [port.role, port])
    );

// export const ALL_PORTS: BasePort[] = [
//   ...DEFAULT_TASK_NODE_PORTS,
//   ...DEFAULT_AGENT_NODE_PORTS,
//   ...DEFAULT_LLM_NODE_PORTS,
//   ...DEFAULT_TOOL_NODE_PORTS,
//   ...DEFAULT_PROJECT_NODE_PORTS,
//   ...DEFAULT_PYTHON_NODE_PORTS,
// ];
