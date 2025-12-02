import { BasePort } from '../../models/port.model';

export const DEFAULT_LLM_NODE_PORTS: BasePort[] = [
  {
    port_type: 'output',

    role: 'llm-out-right',
    multiple: true,
    label: 'Out Right',
    allowedConnections: [
      'agent-llm',
      'agent-function-calling-llm',
      'start-start',
      'edge-in',
      'edge-out',
      'project-in',
      'project-out',
      'python-out',
      'python-in',
      'table-in',
      'subgraph-in',
      'audio-to-text-in',
      'audio-to-text-out',
    ],
    position: 'right',
    color: '#e0575b',
  },

  {
    port_type: 'input',
    role: 'llm-out-left',
    multiple: true,
    label: 'Out Left',
    allowedConnections: [
      'agent-llm',
      'agent-function-calling-llm',
      'start-start',
      'edge-in',
      'edge-out',
      'project-in',
      'project-out',
      'python-out',
      'python-in',
      'subgraph-out',
      'audio-to-text-out',
      'audio-to-text-in',
    ],
    position: 'left',
    color: '#e0575b',
  },
];
