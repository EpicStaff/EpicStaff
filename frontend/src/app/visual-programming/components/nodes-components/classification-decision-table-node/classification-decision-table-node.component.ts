import { CommonModule, NgStyle } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    EventEmitter,
    inject,
    Input,
    Output,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { FFlowModule } from '@foblex/flow';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { NODE_COLORS, NODE_ICONS } from '@shared/models';
import { LlmConfigStorageService, SystemOneConfigStorageService } from '@shared/services';
import { formatNodeLabel } from '@shared/utils';

import { ClickOrDragDirective } from '../../../core/directives/click-or-drag.directive';
import { showsNodeNumber } from '../../../core/helpers/node-number.util';
import { CDT_HEADER_HEIGHT, CDT_ROW_HEIGHT } from '../../../core/helpers/node-size.util';
import {
    buildNodeWarningChip,
    enableTooltipOnlyWhenTruncated,
    NodeWarningBadge,
    nodeWarningChipKind,
} from '../../../core/helpers/node-warning-badge.util';
import {
    fullFileAccessTooltipForSlots,
    NO_FILE_ACCESS_TOOLTIP,
    notConfiguredFileAccessSlots,
} from '../../../core/helpers/storage-grants.util';
import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { ViewPort } from '../../../core/models/port.model';
import { FlowService } from '../../../services/flow.service';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FlowSettingsService } from '../../../services/flow-settings.service';

interface CdtHeaderBadge {
    kind: 'errors' | 'file-access' | 'caution';
    label: string;
    tooltip: string;
    tooltipClass: string;
}

@Component({
    selector: 'app-classification-decision-table-node',
    templateUrl: './classification-decision-table-node.component.html',
    styleUrls: ['./classification-decision-table-node.component.scss'],
    imports: [CommonModule, FormsModule, ClickOrDragDirective, FFlowModule, NgStyle, MATERIAL_FORMS],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClassificationDecisionTableNodeComponent {
    @Input({ required: true }) node!: ClassificationDecisionTableNodeModel;
    @Output() actualClick = new EventEmitter<MouseEvent>();

    private flowService = inject(FlowService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly systemOneConfigStorage = inject(SystemOneConfigStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly flowSettings = inject(FlowSettingsService);
    public readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;
    private readonly flowDiffState = inject(FlowDiffStateService);

    protected readonly nodeColors = NODE_COLORS;
    protected readonly nodeIcons = NODE_ICONS;

    public readonly headerHeightPx = CDT_HEADER_HEIGHT;
    public readonly rowHeightPx = CDT_ROW_HEIGHT;
    protected readonly addedRouteLabel = 'Restore adds this condition';

    constructor() {
        this.llmConfigStorageService.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        this.systemOneConfigStorage.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    get conditionGroups(): ConditionGroup[] {
        const allGroups = this.node.data.table?.condition_groups ?? [];
        return allGroups
            .filter((group: ConditionGroup) => group.valid !== false && group.dock_visible)
            .sort(
                (a: ConditionGroup, b: ConditionGroup) =>
                    (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER)
            );
    }

    /**
     * On a version diff canvas: the routes only the current canvas has, which a restore removes. A port of the
     * shown side without a row (a group with no route code) stays undrawn, as in the live editor.
     */
    get removedRoutePorts(): ViewPort[] {
        if (!this.flowDiffState.isActive()) return [];
        return (this.node.ports ?? []).filter((port) => this.flowDiffState.isCurrentOnlyRoutePort(port.id));
    }

    /** On a version diff canvas: whether the group's route is only in the version, so a restore adds it. */
    protected isAddedRoute(group: ConditionGroup): boolean {
        const port = this.getPortForGroup(group);
        return !!port && this.flowDiffState.isVersionOnlyPort(port.id);
    }

    get defaultNextNode() {
        return this.node.data.table?.default_next_node;
    }

    get defaultNextNodeName(): string | null {
        const idOrName = this.defaultNextNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? formatNodeLabel(node) : idOrName;
    }

    get nextErrorNode() {
        return this.node.data.table?.next_error_node;
    }

    get nextErrorNodeName(): string | null {
        const idOrName = this.nextErrorNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? formatNodeLabel(node) : idOrName;
    }

    readonly noFileAccessTooltip = NO_FILE_ACCESS_TOOLTIP;

    readonly hasNoFileAccessWhenTriggered = computed(() =>
        this.flowService.nodeIdsWithoutFileAccess().has(this.node.id)
    );

    readonly hasFullFileAccessWhenTriggered = computed(() =>
        this.flowService.nodeIdsWithFullFileAccess().has(this.node.id)
    );

    get title(): string {
        return this.node.node_name || 'Classification Table';
    }

    /** Whether the header shows the node's "#N" under the title. */
    protected get isNumberedNode(): boolean {
        return showsNodeNumber(this.node);
    }

    /** The "#N" stays shown under the title; otherwise it appears on hover. */
    protected get isNodeNumberPinned(): boolean {
        return this.isNumberedNode && this.flowSettings.alwaysShowNodeNumbers();
    }

    get inputPort() {
        return this.node.ports?.find((p) => p.port_type === 'input');
    }

    get defaultPort() {
        return this.node.ports?.find((p) => p.role === 'decision-default');
    }

    get errorPort() {
        return this.node.ports?.find((p) => p.role === 'decision-error');
    }

    trackRouteDock(index: number, dock: { code: string; port: ViewPort | undefined }): string {
        return dock.code;
    }

    getPortForRouteCode(routeCode: string) {
        const role = `decision-route-${routeCode}`;
        return this.node.ports?.find((p) => p.role === role);
    }

    trackConditionGroup(index: number, group: ConditionGroup): string {
        const port = this.getPortForGroup(group);
        if (port) {
            return `${index}:${port.id}`;
        }
        if (group.group_name) {
            return `${index}:${group.group_name}`;
        }
        return String(index);
    }

    getPortForGroup(group: ConditionGroup) {
        const key = group.route_code || group.group_name;
        if (!key) {
            return undefined;
        }
        return this.node.ports?.find((p) => p.role === `decision-route-${key}`);
    }

    get hasEmptyConditionName(): boolean {
        const groups: ConditionGroup[] = this.node.data.table?.condition_groups ?? [];
        return groups.some((g: ConditionGroup) => !g.group_name || g.group_name.trim() === '');
    }

    get errorMessages(): string[] {
        const errors: string[] = [];
        if (this.hasMissingLlmConfig) errors.push('LLM config is missing or was deleted');
        if (this.hasMissingSystemOneConfig) errors.push('A System One entry needs a config');
        if (this.hasEmptyConditionName) errors.push('One or more condition groups have an empty Condition Name');
        return errors;
    }

    get errorsTooltip(): string {
        return this.errorMessages.map((m, i) => `${i + 1}. ${m}.`).join(' ');
    }

    get errorsBadgeLabel(): string {
        const n = this.errorMessages.length;
        return n === 1 ? '1 issue' : `${n} issues`;
    }

    /**
     * The one badge the header shows: a lone group of errors, or the missing file access, or a chip when there are
     * several messages (every error plus the file access), listing them one per line; `null` when there is none.
     */
    protected get headerBadge(): CdtHeaderBadge | null {
        const errors = this.errorMessages.map((message) => `${message}.`);
        const hasNoFileAccess = this.hasNoFileAccessWhenTriggered();
        const fullAccessSlots = this.hasFullFileAccessWhenTriggered() ? this.fullFileAccessSlots() : [];
        const hasFullAccess = fullAccessSlots.length > 0;
        const fullAccessTooltip = fullFileAccessTooltipForSlots(fullAccessSlots);
        const badges: NodeWarningBadge[] = [
            ...errors.map((message): NodeWarningBadge => ({ kind: 'warning', label: message, tooltip: message })),
            ...(hasNoFileAccess
                ? [{ kind: 'warning', label: 'No file access', tooltip: this.noFileAccessTooltip } as const]
                : []),
            ...(hasFullAccess
                ? [{ kind: 'caution', label: 'Full file access', tooltip: fullAccessTooltip } as const]
                : []),
        ];
        if (badges.length >= 2) {
            const kind = nodeWarningChipKind(badges) === 'caution' ? 'caution' : 'errors';
            return { kind, ...buildNodeWarningChip(badges.map((badge) => badge.tooltip)) };
        }
        if (errors.length > 0) {
            return { kind: 'errors', label: this.errorsBadgeLabel, tooltip: this.errorsTooltip, tooltipClass: '' };
        }
        if (hasNoFileAccess) {
            return {
                kind: 'file-access',
                label: 'No file access',
                tooltip: this.noFileAccessTooltip,
                tooltipClass: '',
            };
        }
        if (hasFullAccess) {
            return { kind: 'caution', label: 'Full file access', tooltip: fullAccessTooltip, tooltipClass: '' };
        }
        return null;
    }

    private fullFileAccessSlots(): ('pre' | 'post')[] {
        return notConfiguredFileAccessSlots(this.node).filter((slot): slot is 'pre' | 'post' => slot !== 'main');
    }

    protected onTitleHover(tooltip: MatTooltip, nameElement: HTMLElement): void {
        enableTooltipOnlyWhenTruncated(tooltip, nameElement);
    }

    private get promptEntries(): PromptConfig[] {
        return Object.values(this.node.data.table?.prompts ?? {}) as PromptConfig[];
    }

    get hasMissingSystemOneConfig(): boolean {
        const entries = this.promptEntries.filter((prompt) => prompt.kind === 'system_one');
        if (entries.some((prompt) => prompt.system_one_config == null)) return true;

        if (!this.systemOneConfigStorage.isConfigsLoaded()) return false;
        const availableIds = new Set(this.systemOneConfigStorage.configs().map((config) => config.id));
        return entries.some((prompt) => !availableIds.has(prompt.system_one_config as number));
    }

    get hasMissingLlmConfig(): boolean {
        const table = this.node.data.table;
        if (!table) return false;

        // A prompt with no LLM config selected is always considered missing,
        // regardless of whether the available-configs list has loaded yet.
        if (table.prompts) {
            for (const prompt of this.promptEntries) {
                if (prompt.kind !== 'system_one' && prompt.llm_config == null) return true;
            }
        }

        // Deleted-config detection requires the configs list to be loaded.
        if (!this.llmConfigStorageService.isConfigsLoaded()) return false;
        const availableIds = new Set(this.llmConfigStorageService.configs().map((c) => c.id));

        if (table.default_llm_config != null && !availableIds.has(table.default_llm_config)) {
            return true;
        }
        if (table.prompts) {
            for (const prompt of this.promptEntries) {
                if (prompt.kind !== 'system_one' && prompt.llm_config != null && !availableIds.has(prompt.llm_config))
                    return true;
            }
        }
        return false;
    }

    onEditClick() {
        this.actualClick.emit();
    }
}
