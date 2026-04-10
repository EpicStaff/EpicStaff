import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { ConditionGroup } from '../models/decision-table.model';
import { BaseNodeModel } from '../models/node.model';
import { BasePort, CustomPortId, ViewPort } from '../models/port.model';
import { PORTS_DICTIONARY } from '../rules/all_ports';
import { DEFAULT_AUDIO_TO_TEXT_NODE_PORTS } from '../rules/audio-to-text-node-ports/audio-to-text-node-ports';
import { DEFAULT_CODE_AGENT_NODE_PORTS } from '../rules/code-agent-ports/code-agent-node-default-ports';
import { DEFAULT_EDGE_NODE_PORTS } from '../rules/edge-ports/edge-node-default-ports';
import { DEFAULT_END_NODE_PORTS } from '../rules/end-ports/end-ports-default-ports';
import { DEFAULT_FILE_EXTRACTOR_NODE_PORTS } from '../rules/file-extractor-ports/file-extractor-default-ports';
import { DEFAULT_LLM_NODE_PORTS } from '../rules/llm-ports/llm-node-default-ports';
import { DEFAULT_PROJECT_NODE_PORTS } from '../rules/project-ports/project-node-default-ports';
import { DEFAULT_PYTHON_NODE_PORTS } from '../rules/python-ports/python-node-default-ports';
import { DEFAULT_START_NODE_PORTS } from '../rules/start-ports/start-node-default-ports';
import { DEFAULT_SUBGRAPH_NODE_PORTS } from '../rules/subgraph-ports/subgraph-node-default-ports';
import { DEFAULT_TABLE_NODE_PORTS } from '../rules/table-ports/table-ports';
import { DEFAULT_TASK_NODE_PORTS } from '../rules/task-ports/task-node-defaults-ports';
import { DEFAULT_TELEGRAM_TRIGGER_NODE_PORTS } from '../rules/telegram-trigger-ports/telegram-trigger-default-ports';
import { DEFAULT_TOOL_NODE_PORTS } from '../rules/tool-ports/tool-node-default-ports';
import { DEFAULT_WEBHOOK_TRIGGER_NODE_PORTS } from '../rules/webhook-trigger-ports/webhook-trigger-default-ports';

export const isDecisionPortRole = (role: string) =>
    role.startsWith('decision-out-') || role === 'decision-default' || role === 'decision-error';

export function parsePortId(portId: string): { nodeId: string; portRole: string } | null {
    const underscoreIndex = portId.indexOf('_');
    if (underscoreIndex === -1) return null;
    const nodeId = portId.substring(0, underscoreIndex);
    let portRole = portId.substring(underscoreIndex + 1);

    // If a colon exists, only keep the part before it.
    const colonIndex = portRole.indexOf(':');
    if (colonIndex !== -1) {
        portRole = portRole.substring(0, colonIndex);
    }

    return { nodeId, portRole };
}

export function getPortsForType(nodeType: NodeType): BasePort[] {
    switch (nodeType) {
        case NodeType.TASK:
            return DEFAULT_TASK_NODE_PORTS;
        case NodeType.LLM:
            return DEFAULT_LLM_NODE_PORTS;
        case NodeType.TOOL:
            return DEFAULT_TOOL_NODE_PORTS;
        case NodeType.PROJECT:
            return DEFAULT_PROJECT_NODE_PORTS;
        case NodeType.PYTHON:
            return DEFAULT_PYTHON_NODE_PORTS;
        case NodeType.EDGE:
            return DEFAULT_EDGE_NODE_PORTS;
        case NodeType.START:
            return DEFAULT_START_NODE_PORTS;
        case NodeType.TABLE:
            return DEFAULT_TABLE_NODE_PORTS;
        case NodeType.FILE_EXTRACTOR:
            return DEFAULT_FILE_EXTRACTOR_NODE_PORTS;
        case NodeType.AUDIO_TO_TEXT:
            return DEFAULT_AUDIO_TO_TEXT_NODE_PORTS;
        case NodeType.WEBHOOK_TRIGGER:
            return DEFAULT_WEBHOOK_TRIGGER_NODE_PORTS;
        case NodeType.TELEGRAM_TRIGGER:
            return DEFAULT_TELEGRAM_TRIGGER_NODE_PORTS;
        case NodeType.END:
            return DEFAULT_END_NODE_PORTS;
        case NodeType.SUBGRAPH:
            return DEFAULT_SUBGRAPH_NODE_PORTS;
        case NodeType.CODE_AGENT:
            return DEFAULT_CODE_AGENT_NODE_PORTS;
        case NodeType.NOTE:
            return [];
        default:
            console.warn(`Unsupported node type: ${nodeType}`);
            return [];
    }
}

export function getPortByRole(portRole: string): BasePort | undefined {
    const port = PORTS_DICTIONARY[portRole];
    if (!port && !isDecisionPortRole(portRole)) {
        console.warn(`No port definition found for role: "${portRole}"`);
    }
    return port;
}

export function isConnectionValid(sourcePortId: CustomPortId, targetPortId: CustomPortId): boolean {
    // 1️⃣ Parse the port IDs
    const sourceInfo = parsePortId(sourcePortId);
    const targetInfo = parsePortId(targetPortId);

    if (!sourceInfo || !targetInfo) {
        console.warn(`Could not parse portId(s): ${sourcePortId}, ${targetPortId}`);
        return false;
    }

    // 2️⃣ Look up BasePort definitions
    let sourcePort = getPortByRole(sourceInfo.portRole);
    let targetPort = getPortByRole(targetInfo.portRole);

    // Handle dynamic decision table output ports
    if (!sourcePort && isDecisionPortRole(sourceInfo.portRole)) {
        sourcePort = {
            ...DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'output')!,
            role: sourceInfo.portRole,
        };
    }
    if (!targetPort && isDecisionPortRole(targetInfo.portRole)) {
        targetPort = {
            ...DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'output')!,
            role: targetInfo.portRole,
        };
    }

    if (!sourcePort || !targetPort) {
        console.warn('One or both ports could not be found in PORTS_DICTIONARY:', {
            sourcePortId,
            targetPortId,
            sourceRole: sourceInfo.portRole,
            targetRole: targetInfo.portRole,
        });
        return false;
    }

    if (sourceInfo.nodeId === targetInfo.nodeId) {
        console.warn(`Cannot connect a node to itself: ${sourceInfo.nodeId}`);
        return false;
    }

    // 4️⃣ Disallow input→input or output→output
    if (
        (sourcePort.port_type === 'input' && targetPort.port_type === 'input') ||
        (sourcePort.port_type === 'output' && targetPort.port_type === 'output')
    ) {
        console.warn(`Cannot connect two ports of the same type: ${sourcePort.port_type}-${targetPort.port_type}`);
        return false;
    }

    // 5️⃣ Validate allowedConnections
    const sourceAllowsTarget = sourcePort.allowedConnections.some((allowed) => {
        if (allowed === targetPort.role) return true;
        if (allowed === 'table-out' && isDecisionPortRole(targetInfo.portRole)) return true;
        return false;
    });

    const targetAllowsSource = targetPort.allowedConnections.some((allowed) => {
        if (allowed === sourcePort.role) return true;
        if (allowed === 'table-out' && isDecisionPortRole(sourceInfo.portRole)) return true;
        return false;
    });

    if (!sourceAllowsTarget || !targetAllowsSource) {
        console.warn(
            `Invalid connection roles: "${sourcePort.role}" -> "${targetPort.role}".
         sourceAllowsTarget=${sourceAllowsTarget}, targetAllowsSource=${targetAllowsSource}`
        );
        return false;
    }

    // 🎉 If we reach here, it's valid
    return true;
}

export function defineSourceTargetPair(
    portIdA: CustomPortId,
    portIdB: CustomPortId
): { sourcePortId: CustomPortId; targetPortId: string } | null {
    // 1️⃣ Parse port IDs to get roles
    const parsedA = parsePortId(portIdA);
    const parsedB = parsePortId(portIdB);

    if (!parsedA || !parsedB) {
        console.warn('Could not parse one or both port IDs:', portIdA, portIdB);
        return null;
    }

    // 2️⃣ Look up their definitions in PORTS_DICTIONARY
    let portA: BasePort | undefined = getPortByRole(parsedA.portRole);
    let portB: BasePort | undefined = getPortByRole(parsedB.portRole);

    // Handle dynamic decision table output ports
    if (!portA && isDecisionPortRole(parsedA.portRole)) {
        portA = {
            ...DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'output')!,
            role: parsedA.portRole,
        };
    }
    if (!portB && isDecisionPortRole(parsedB.portRole)) {
        portB = {
            ...DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'output')!,
            role: parsedB.portRole,
        };
    }

    if (!portA || !portB) {
        console.warn('Could not find one or both ports:', { portIdA, portIdB });
        return null;
    }

    // 3️⃣ Determine which is source (output) and which is target (input)
    if (portA.port_type === 'output' && portB.port_type === 'input') {
        return {
            sourcePortId: portIdA,
            targetPortId: portIdB,
        };
    }

    if (portA.port_type === 'input' && portB.port_type === 'output') {
        return {
            sourcePortId: portIdB,
            targetPortId: portIdA,
        };
    }

    console.warn(`Unsupported port types: portA.type=${portA.port_type}, portB.type=${portB.port_type}`);
    return null;
}

export function generatePortsForNode(newNodeId: string, nodeType: NodeType, data?: unknown): ViewPort[] {
    if (nodeType === NodeType.TABLE) {
        // Defensive: check for data.table.condition_groups
        const tableData =
            (
                data as {
                    table?: {
                        condition_groups?: ConditionGroup[];
                        default_next_node?: unknown;
                        next_error_node?: unknown;
                    };
                }
            )?.table ?? {};
        const conditionGroups: ConditionGroup[] = tableData?.condition_groups ?? [];
        return generatePortsForDecisionTableNode(newNodeId, conditionGroups);
    }
    const portsConfig: BasePort[] = getPortsForType(nodeType);
    return portsConfig.map((config) => ({
        ...config,
        id: `${newNodeId}_${config.role}`,
    }));
}

export function generatePortsForDecisionTableNode(nodeId: string, conditionGroups: ConditionGroup[]): ViewPort[] {
    // Use the default input port from DEFAULT_TABLE_NODE_PORTS
    const inputPortConfig = DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'input');
    const inputPort = {
        ...(inputPortConfig ?? {
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
                'file-extractor-out',
            ],
            position: 'left',
            color: '#00aaff',
        }),
        id: `${nodeId}_table-in` as `${string}_${string}`,
    };

    const validGroups = conditionGroups
        .filter((group) => group.valid !== false)
        .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER));

    const defaultOutputConfig = DEFAULT_TABLE_NODE_PORTS.find((p) => p.port_type === 'output');
    const outputPorts: ViewPort[] = validGroups.map((group) => {
        const normalizedGroupName = group.group_name.toLowerCase().replace(/\s+/g, '-');

        return {
            ...(defaultOutputConfig ?? {
                port_type: 'output',
                allowedConnections: [
                    'project-in',
                    'python-in',
                    'edge-in',
                    'table-in',
                    'llm-out-left',
                    'end-in',
                    'decision-out-in',
                    'file-extractor-in',
                ],
                position: 'right',
                color: '#00aaff',
                multiple: false,
            }),
            role: `decision-out-${group.group_name}`,
            label: group.group_name,
            id: `${nodeId}_decision-out-${normalizedGroupName}` as `${string}_${string}`,
        };
    });

    const specialPorts: ViewPort[] = [];

    if (defaultOutputConfig) {
        specialPorts.push({
            ...defaultOutputConfig,
            role: 'decision-default',
            label: 'Default',
            id: `${nodeId}_decision-default` as `${string}_${string}`,
        });

        specialPorts.push({
            ...defaultOutputConfig,
            role: 'decision-error',
            label: 'Error',
            id: `${nodeId}_decision-error` as `${string}_${string}`,
        });
    }

    return [inputPort, ...outputPorts, ...specialPorts];
}

type ConnectionLayout = 'horizontal' | 'vertical' | 'mixed';

const LAYOUT_DOMINANCE_RATIO = 1.2;
const MIN_VERTICAL_GAP = 25;
const MIN_OVERLAP_RATIO_FOR_VERTICAL = 0.1;

function isHorizontalPort(position?: string): boolean {
    return position === 'left' || position === 'right';
}

function isVerticalPort(position?: string): boolean {
    return position === 'top' || position === 'bottom';
}

function getNodeCenter(node: BaseNodeModel): { x: number; y: number } {
    return {
        x: node.position.x + node.size.width / 2,
        y: node.position.y + node.size.height / 2,
    };
}

function getHorizontalOverlap(source: BaseNodeModel, target: BaseNodeModel): number {
    const sourceLeft = source.position.x;
    const sourceRight = source.position.x + source.size.width;
    const targetLeft = target.position.x;
    const targetRight = target.position.x + target.size.width;

    return Math.max(0, Math.min(sourceRight, targetRight) - Math.max(sourceLeft, targetLeft));
}

function getConnectionLayout(
    source: BaseNodeModel,
    target: BaseNodeModel,
    sourcePort?: ViewPort,
    targetPort?: ViewPort
): ConnectionLayout {
    const sourceCenter = getNodeCenter(source);
    const targetCenter = getNodeCenter(target);

    const dx = Math.abs(targetCenter.x - sourceCenter.x);
    const dy = Math.abs(targetCenter.y - sourceCenter.y);

    const overlapX = getHorizontalOverlap(source, target);
    const minWidth = Math.min(source.size.width, target.size.width);
    const overlapRatio = minWidth > 0 ? overlapX / minWidth : 0;

    if (dy >= MIN_VERTICAL_GAP && overlapRatio >= MIN_OVERLAP_RATIO_FOR_VERTICAL) {
        return 'vertical';
    }

    if (dx > dy * LAYOUT_DOMINANCE_RATIO) {
        return 'horizontal';
    }

    if (dy > dx * LAYOUT_DOMINANCE_RATIO) {
        return 'vertical';
    }

    const bothVerticalPorts = isVerticalPort(sourcePort?.position) && isVerticalPort(targetPort?.position);

    const bothHorizontalPorts = isHorizontalPort(sourcePort?.position) && isHorizontalPort(targetPort?.position);

    if (bothVerticalPorts) {
        return 'vertical';
    }

    if (bothHorizontalPorts) {
        return 'horizontal';
    }

    return 'mixed';
}

export function isBackwardConnection(connection: ConnectionModel, nodes: BaseNodeModel[]): boolean {
    const source = nodes.find((n) => n.id === connection.sourceNodeId);
    const target = nodes.find((n) => n.id === connection.targetNodeId);
    if (!source || !target) return false;

    const sourcePort = source.ports?.find((p) => p.id === connection.sourcePortId);
    const targetPort = target.ports?.find((p) => p.id === connection.targetPortId);

    const layout = getConnectionLayout(source, target, sourcePort, targetPort);

    if (layout === 'horizontal') {
        const sourceExitX = sourcePort?.position === 'left' ? source.position.x : source.position.x + source.size.width;

        const targetEntryX =
            targetPort?.position === 'right' ? target.position.x + target.size.width : target.position.x;

        return sourceExitX > targetEntryX;
    }

    if (layout === 'vertical') {
        const sourceExitY = sourcePort?.position === 'top' ? source.position.y : source.position.y + source.size.height;

        const targetEntryY =
            targetPort?.position === 'bottom' ? target.position.y + target.size.height : target.position.y;

        return sourceExitY > targetEntryY;
    }

    const bothHorizontalPorts = isHorizontalPort(sourcePort?.position) && isHorizontalPort(targetPort?.position);

    const bothVerticalPorts = isVerticalPort(sourcePort?.position) && isVerticalPort(targetPort?.position);

    if (bothHorizontalPorts) {
        const sourceExitX = sourcePort?.position === 'left' ? source.position.x : source.position.x + source.size.width;

        const targetEntryX =
            targetPort?.position === 'right' ? target.position.x + target.size.width : target.position.x;

        return sourceExitX > targetEntryX;
    }

    if (bothVerticalPorts) {
        const sourceExitY = sourcePort?.position === 'top' ? source.position.y : source.position.y + source.size.height;

        const targetEntryY =
            targetPort?.position === 'bottom' ? target.position.y + target.size.height : target.position.y;

        return sourceExitY > targetEntryY;
    }

    return false;
}
