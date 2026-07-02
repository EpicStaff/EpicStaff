import { ConfirmationDialogData } from '../../../shared/components/cofirm-dialog/confirmation-dialog.component';
import { AgentDefinition } from '../models/agent-definition.model';
import { Surface } from '../models/surface.model';

export interface DeleteUsageCounts {
    agents: number;
    flows: number;
    chats: number;
}

export interface SurfaceBundleCounts {
    tools: number;
    files: number;
    collections: number;
}

export function surfaceBundleCounts(surface: Surface): SurfaceBundleCounts {
    return {
        tools: surface.python_tools.length + surface.mcp_tools.length,
        files: surface.storage_items.length,
        collections: surface.knowledge.length,
    };
}

function formatCount(n: number, singular: string, plural: string): string {
    return `${n} ${n === 1 ? singular : plural}`;
}

function joinWithAnd(parts: string[]): string {
    if (parts.length === 0) return '';
    if (parts.length === 1) return parts[0];
    if (parts.length === 2) return `${parts[0]} and ${parts[1]}`;
    return `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`;
}

function buildUsageParts(counts: DeleteUsageCounts): string[] {
    const parts: string[] = [];
    if (counts.agents > 0) parts.push(formatCount(counts.agents, 'agent', 'agents'));
    if (counts.flows > 0) parts.push(formatCount(counts.flows, 'flow', 'flows'));
    if (counts.chats > 0) parts.push(formatCount(counts.chats, 'chat', 'chats'));
    return parts;
}

function buildAccessPhrase(bundle: SurfaceBundleCounts): string {
    const parts: string[] = [];
    if (bundle.tools > 0) parts.push(formatCount(bundle.tools, 'tool', 'tools'));
    if (bundle.files > 0) parts.push(formatCount(bundle.files, 'file', 'files'));
    if (bundle.collections > 0) parts.push(formatCount(bundle.collections, 'collection', 'collections'));
    if (!parts.length) return '';
    return `access to ${joinWithAnd(parts)}`;
}

function buildSurfaceDeleteCaution(usage: DeleteUsageCounts, bundle: SurfaceBundleCounts, shared: boolean): string {
    const usageParts = buildUsageParts(usage);
    const access = buildAccessPhrase(bundle);

    if (shared) {
        let caution = 'If you delete it, it will be removed from all locations where it is used';
        if (usageParts.length) caution += ` (${joinWithAnd(usageParts)})`;
        if (access) caution += ` and ${access} will be lost.`;
        else caution += '.';
        return caution;
    }

    let caution = 'If you delete it now, this Surface will be removed';
    if (usageParts.length) caution += ` from ${joinWithAnd(usageParts)}`;
    if (access) {
        caution += usageParts.length
            ? `, and ${access} will be permanently lost.`
            : ` and ${access} will be permanently lost.`;
    } else {
        caution += usageParts.length ? '.' : ' permanently.';
    }
    return caution;
}

function buildAgentDeleteCaution(usage: DeleteUsageCounts): string {
    const usageParts = buildUsageParts(usage);
    if (!usageParts.length) {
        return 'If you delete now, this agent will be permanently removed and all agent settings and configurations will be lost.';
    }
    return `If you delete now, this agent will be permanently removed from all locations where it is used—including ${joinWithAnd(usageParts)}—and all agent settings and configurations will be lost.`;
}

export function isAgentDeployed(agent: AgentDefinition, ownedSurfaceCount: number): boolean {
    return agent.default_surfaces.length > 0 || ownedSurfaceCount > 0;
}

export function buildDeleteAgentDialog(
    agent: AgentDefinition,
    usage: DeleteUsageCounts,
    ownedSurfaceCount: number
): ConfirmationDialogData {
    const deployed = isAgentDeployed(agent, ownedSurfaceCount) || usage.flows > 0 || usage.chats > 0;
    return {
        title: 'Delete Agent?',
        message: deployed
            ? 'This agent is currently deployed and active across multiple locations.'
            : 'You are about to remove this agent from the system.',
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
        cautionTitle: 'Caution',
        caution: buildAgentDeleteCaution(usage),
        isShownBorder: true,
    };
}

export function buildDeleteSurfaceDialog(
    surface: Surface,
    usage: DeleteUsageCounts,
    shared: boolean
): ConfirmationDialogData {
    const bundle = surfaceBundleCounts(surface);
    return {
        title: shared ? 'Delete Shared Surface?' : 'Delete Surface?',
        message: shared
            ? 'You are about to remove this shared permission group.'
            : 'You are about to remove this permission group and instructions.',
        confirmText: 'Delete',
        cancelText: 'Cancel',
        type: 'danger',
        cautionTitle: shared ? 'Caution' : 'Attention',
        caution: buildSurfaceDeleteCaution(usage, bundle, shared),
        isShownBorder: true,
    };
}

export const DELETE_CONFIRM_DIALOG_WIDTH = '485px';
