import { BasePort } from '../../models/port.model';

export const DEFAULT_TASK_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'task-previous-task-with-context',
        multiple: true,
        label: 'Prev. Task with Context',
        allowedConnections: [],
        position: 'left',
        color: '#30a46c', // TASK color
    },
    {
        port_type: 'input',
        role: 'task-agent',
        multiple: false,
        label: 'Agent',
        allowedConnections: ['agent-tasks'],
        position: 'top',
        color: '#8e5cd9', // AGENT color
    },
    {
        port_type: 'output',
        role: 'task-callback',
        multiple: false,
        label: 'Task callback',
        allowedConnections: [],
        position: 'top',
        color: '#30a46c', // TASK color
    },
    {
        port_type: 'output',
        role: 'task-next-task',
        multiple: false,
        label: 'Next task',
        allowedConnections: ['task-previous-task'],
        position: 'right',
        color: '#30a46c', // TASK color
    },
    {
        port_type: 'output',
        role: 'task-next-task-with-context',
        multiple: true,
        label: 'Next task with context',
        allowedConnections: [],
        position: 'right',
        color: '#30a46c', // TASK color
    },
    {
        port_type: 'output',
        role: 'task-tools',
        multiple: true,
        label: 'Tools',
        allowedConnections: [],
        position: 'bottom',
        color: '#9f6a00', // TOOL color
    },
    {
        port_type: 'output',
        role: 'task-output-log-file',
        multiple: true,
        label: 'Output log file',
        allowedConnections: [],
        position: 'bottom',
        color: '#30a46c', // TASK color
    },
    {
        port_type: 'input',
        role: 'task-previous-task',
        multiple: false,
        label: 'Prev. Task',
        allowedConnections: ['task-next-task'],
        position: 'left',
        color: '#30a46c', // TASK color
    },
];
