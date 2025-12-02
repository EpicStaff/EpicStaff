import { BasePort } from '../../models/port.model';

export const DEFAULT_TABLE_NODE_PORTS: BasePort[] = [
  {
    port_type: 'input',
    role: 'table-in',
    multiple: true,
    label: 'In',
    allowedConnections: [
      'project-out',
      'python-out',
      'edge-out',
      'table-out',
      'start-start',
      'llm-out-right',
      'audio-to-text-out',
      'webhook-trigger-out',
    ],
    position: 'left',
    color: '#00aaff',
  },
  {
    port_type: 'output',
    role: 'table-out',
    multiple: false,
    label: 'Out',
    allowedConnections: [
      'project-in',
      'python-in',
      'edge-in',
      'table-in',
      'llm-out-left',
      'audio-to-text-in',
      'end-in',
      'webhook-trigger-in',
      'file-extractor-in',
    ],
    position: 'right',
    color: '#00aaff',
  },
];
