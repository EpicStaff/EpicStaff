import { BasePort } from '../../models/port.model';

export const DEFAULT_AUDIO_TO_TEXT_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'audio-to-text-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'edge-out',
            'start-start',
            'table-out',
            'llm-out-right',
            'file-extractor-out',
            'audio-to-text-out',
        ],
        position: 'left',
        color: '#ff7be9ff',
    },

    {
        port_type: 'output',
        role: 'audio-to-text-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'table-in',
            'llm-out-left',
            'file-extractor-in',
            'end-in',
            'audio-to-text-in',
        ],
        position: 'right',
        color: '#ff7be9ff',
    },
];
