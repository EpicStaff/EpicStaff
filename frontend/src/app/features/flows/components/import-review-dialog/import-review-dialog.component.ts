import { animate, state, style, transition, trigger } from '@angular/animations';
import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    Inject,
    inject,
    QueryList,
    signal,
    ViewChild,
    ViewChildren,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ButtonComponent, FlowNodeListComponent, FlowNodeListItem } from '@shared/components';

import { EntityTypeResult, ImportResult, ImportResultItem } from '../../../../core/models/import-result.model';
import {
    FlowNodesByFile,
    ImportReviewDialogCloseResult,
    ImportReviewDialogData,
    mapBackendNodeType,
    ReviewItem,
    ReviewPythonCode,
} from '../../../../core/models/review-item.model';
import { ToastService } from '../../../../services/notifications/toast.service';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { DEFAULT_ENTITY_ICON, ENTITY_ICONS } from '../../../../shared/constants/entity-icons.constants';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import {
    CodeFileDetailsDialogComponent,
    CodeFileDetailsDialogData,
} from '../code-file-details-dialog/code-file-details-dialog.component';

interface FlowReviewNode extends FlowNodeListItem {
    key: string;
    fieldKeys: string[];
    codes: ReviewPythonCode[];
    fieldLabels: (string | null)[];
    codeFieldCount: number;
}

interface CodeTab {
    label: string;
    fieldKey: string;
}

interface ReviewableEntry {
    title: string;
    fieldKey: string;
    code: ReviewPythonCode;
    codeTabs: CodeTab[];
}

const FLOW_NODE_TYPE_LABELS: Partial<Record<NodeType, string>> = {
    [NodeType.PYTHON]: 'Python Node',
    [NodeType.CLASSIFICATION_TABLE]: 'CDT',
    [NodeType.WEBHOOK_TRIGGER]: 'Webhook Node',
    [NodeType.TELEGRAM_TRIGGER]: 'Telegram Node',
    [NodeType.AGENT]: 'Agent Node',
    [NodeType.TASK]: 'Task Node',
};

@Component({
    selector: 'app-import-review-dialog',
    standalone: true,
    imports: [
        CommonModule,
        AppIconComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        ButtonComponent,
        FlowNodeListComponent,
        CodeEditorComponent,
    ],
    templateUrl: './import-review-dialog.component.html',
    styleUrls: ['./import-review-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('220ms ease')),
        ]),
    ],
})
export class ImportReviewDialogComponent implements AfterViewInit {
    private sanitizer = inject(DomSanitizer);
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private toastService = inject(ToastService);

    @ViewChild('summaryList') summaryListRef!: ElementRef<HTMLElement>;
    @ViewChild('entityListsSection') entityListsSectionRef!: ElementRef<HTMLElement>;
    @ViewChildren('entityGroup') entityGroupRefs!: QueryList<ElementRef<HTMLElement>>;
    @ViewChild('codeEditor') codeEditorRef?: CodeEditorComponent;

    private readonly SCROLL_STEP = 240;
    private _scrollLeft = signal(0);
    private _scrollWidth = signal(0);
    private _clientWidth = signal(0);

    public canScrollLeft = computed(() => this._scrollLeft() > 0);
    public canScrollRight = computed(() => this._scrollLeft() < this._scrollWidth() - this._clientWidth() - 1);

    public importResult: ImportResult;
    public expandedItems = signal<Set<string>>(new Set());
    public highlightedGroup = signal<string | null>(null);
    private _highlightTimeout: ReturnType<typeof setTimeout> | null = null;

    private readonly HIDDEN_ENTITY_TYPES = new Set(['LLMModelTag']);

    private readonly ENTITY_TYPE_ORDER = [
        'Tool',
        'Flow',
        'Project',
        'Agent',
        'LLMModel',
        'LLMConfig',
        'RealtimeModel',
        'RealtimeConfig',
    ];

    public totalItemsCount = computed(() => {
        let total = 0;
        Object.entries(this.importResult).forEach(([key, result]) => {
            if (result && !this.HIDDEN_ENTITY_TYPES.has(key)) total += result.total;
        });
        return total;
    });

    public entityTypes = computed(() => {
        const keys = new Set(Object.keys(this.importResult).filter((k) => !this.HIDDEN_ENTITY_TYPES.has(k)));
        if (keys.has('PythonCodeTool') || keys.has('MCPTool')) {
            keys.delete('PythonCodeTool');
            keys.delete('MCPTool');
            keys.add('Tool');
        }
        return Array.from(keys).sort((a, b) => {
            const ai = this.ENTITY_TYPE_ORDER.indexOf(a);
            const bi = this.ENTITY_TYPE_ORDER.indexOf(b);
            if (ai === -1 && bi === -1) return a.localeCompare(b);
            if (ai === -1) return 1;
            if (bi === -1) return -1;
            return ai - bi;
        });
    });

    public visibleEntityTypes = computed(() => {
        return this.entityTypes().filter((et) => this.getEntityTypeCount(et) > 0);
    });

    public readonly isSingleGroup = computed(() => this.visibleEntityTypes().length <= 1);

    public readonly reviewItems: ReviewItem[];
    public readonly nodeTypeLabels = FLOW_NODE_TYPE_LABELS;
    private readonly flowNodesByName: Map<string, FlowReviewNode[]>;
    private readonly pythonCodeToolCodes: Map<string, ReviewPythonCode>;
    public readonly reviewedNodeKeys = signal<Set<string>>(new Set());

    public readonly reviewableEntries: ReviewableEntry[];
    public readonly currentReviewIndex = signal(0);
    public readonly currentReviewEntry = computed(() => this.reviewableEntries[this.currentReviewIndex()] ?? null);

    constructor(
        public dialogRef: DialogRef<ImportReviewDialogCloseResult>,
        @Inject(DIALOG_DATA) public data: ImportReviewDialogData
    ) {
        this.importResult = data.importResult;
        this.reviewItems = data.reviewItems ?? [];
        this.flowNodesByName = this.buildFlowNodesByName(this.reviewItems, data.allFlowNodes ?? {});
        this.pythonCodeToolCodes = new Map(
            this.reviewItems
                .filter((item) => item.kind === 'python_code_tool')
                .map((item) => [item.name, item.python_code] as const)
        );
        this.reviewableEntries = this.buildReviewableEntries();

        if (this.reviewableEntries.length === 1) {
            this.reviewedNodeKeys.set(new Set([this.reviewableEntries[0].fieldKey]));
        }
    }

    private buildReviewableEntries(): ReviewableEntry[] {
        const entries: ReviewableEntry[] = [];
        for (const [name, code] of this.pythonCodeToolCodes) {
            entries.push({ title: name, fieldKey: this.toolReviewKey(name), code, codeTabs: [] });
        }
        for (const nodes of this.flowNodesByName.values()) {
            for (const node of nodes) {
                const codeTabs: CodeTab[] = node.fieldLabels
                    .map((label, i) => (label ? { label, fieldKey: node.fieldKeys[i] } : null))
                    .filter((tab): tab is CodeTab => tab !== null);

                node.fieldKeys.forEach((fieldKey, i) => {
                    entries.push({ title: node.name, fieldKey, code: node.codes[i], codeTabs });
                });
            }
        }
        return entries;
    }

    public goToCodeTab(fieldKey: string): void {
        const index = this.reviewableEntries.findIndex((entry) => entry.fieldKey === fieldKey);
        if (index !== -1) this.currentReviewIndex.set(index);
    }

    public onFlowNodeRowClick(node: FlowReviewNode): void {
        if (node.codeFieldCount === 0) return;
        this.goToCodeTab(node.fieldKeys[0]);
    }

    public goToPreviousReviewEntry(): void {
        const total = this.reviewableEntries.length;
        if (total === 0) return;
        this.currentReviewIndex.update((i) => (i - 1 + total) % total);
    }

    public goToNextReviewEntry(): void {
        const total = this.reviewableEntries.length;
        if (total === 0) return;
        const entry = this.currentReviewEntry();
        if (entry) this.markReviewedKey(entry.fieldKey);
        this.currentReviewIndex.update((i) => (i + 1) % total);
    }

    public librariesCount(code: ReviewPythonCode | undefined): number {
        return code?.libraries.split(/\s+/).filter(Boolean).length ?? 0;
    }

    private librariesList(code: ReviewPythonCode): string[] {
        return code.libraries.split(/\s+/).filter(Boolean);
    }

    public openFileDetails(entry: ReviewableEntry): void {
        this.dialog.open<void, CodeFileDetailsDialogData>(CodeFileDetailsDialogComponent, {
            data: {
                entrypoint: entry.code.entrypoint,
                libraries: this.librariesList(entry.code),
            },
        });
    }

    public copyCurrentCode(): void {
        this.codeEditorRef?.copyCode();
    }

    private buildFlowNodesByName(
        reviewItems: ReviewItem[],
        allFlowNodes: FlowNodesByFile
    ): Map<string, FlowReviewNode[]> {
        interface CodeField {
            label: string | null;
            code: ReviewPythonCode;
        }
        const fieldsByNode = new Map<string, CodeField[]>();
        for (const item of reviewItems) {
            if (item.kind !== 'flow_node') continue;
            const name = item.node_name ?? 'Untitled node';
            const fields: CodeField[] = [];
            if (item.python_code) fields.push({ label: null, code: item.python_code });
            if (item.pre_python_code) fields.push({ label: 'Pre-computation', code: item.pre_python_code });
            if (item.post_python_code) fields.push({ label: 'Post-computation', code: item.post_python_code });
            fieldsByNode.set(`${item.flow_name}::${name}`, fields);
        }

        const map = new Map<string, FlowReviewNode[]>();
        for (const [flowName, nodes] of Object.entries(allFlowNodes)) {
            const list = nodes.map((node): FlowReviewNode => {
                const key = `${flowName}::${node.name}`;
                const nodeType = mapBackendNodeType(node.node_type) ?? NodeType.PYTHON;
                const fields = fieldsByNode.get(key) ?? [];
                const fieldKeys = fields.map((_, i) => `${key}::${i}`);
                const codes = fields.map((field) => field.code);
                const fieldLabels = fields.map((field) => field.label);
                return {
                    key,
                    name: node.name,
                    nodeType,
                    codeFieldCount: fields.length,
                    fieldKeys,
                    codes,
                    fieldLabels,
                };
            });
            map.set(flowName, list);
        }
        return map;
    }

    public flowNodes(flowName: string): FlowReviewNode[] {
        return this.flowNodesByName.get(flowName) ?? [];
    }

    public hasReviewNodes(flowName: string): boolean {
        return this.flowNodes(flowName).length > 0;
    }

    public isNodeReviewed(node: FlowReviewNode): boolean {
        return this.nodeReviewedFieldCount(node) === node.codeFieldCount;
    }

    public nodeReviewedFieldCount(node: FlowReviewNode): number {
        const reviewed = this.reviewedNodeKeys();
        return node.fieldKeys.filter((key) => reviewed.has(key)).length;
    }

    public nodeRemainingFieldCount(node: FlowReviewNode): number {
        return node.codeFieldCount - this.nodeReviewedFieldCount(node);
    }

    public toggleNodeReviewed(node: FlowReviewNode): void {
        const reviewed = this.reviewedNodeKeys();
        const nextUnreviewed = node.fieldKeys.find((key) => !reviewed.has(key));

        const next = new Set(reviewed);
        if (nextUnreviewed) {
            next.add(nextUnreviewed);
        } else {
            node.fieldKeys.forEach((key) => next.delete(key));
        }
        this.reviewedNodeKeys.set(next);
    }

    private toggleReviewedKey(key: string): void {
        const next = new Set(this.reviewedNodeKeys());
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.reviewedNodeKeys.set(next);
    }

    private markReviewedKey(key: string): void {
        if (this.reviewedNodeKeys().has(key)) return;
        this.reviewedNodeKeys.update((current) => new Set(current).add(key));
    }

    public hasPythonCode(name: string): boolean {
        return this.pythonCodeToolCodes.has(name);
    }

    public toolTransport(item: ImportResultItem): string | null {
        const val = (item as unknown as Record<string, unknown>)['transport'];
        return typeof val === 'string' && val ? val : null;
    }

    private toolReviewKey(name: string): string {
        return `tool::${name}`;
    }

    public isToolReviewed(name: string): boolean {
        return this.reviewedNodeKeys().has(this.toolReviewKey(name));
    }

    public toggleToolReviewed(name: string): void {
        this.toggleReviewedKey(this.toolReviewKey(name));
    }

    public flowReviewTotal(flowName: string): number {
        return this.flowNodes(flowName).reduce((sum, node) => sum + node.codeFieldCount, 0);
    }

    public flowReviewRemaining(flowName: string): number {
        return this.flowNodes(flowName).reduce((sum, node) => sum + this.nodeRemainingFieldCount(node), 0);
    }

    public isFlowFullyReviewed(flowName: string): boolean {
        return this.flowReviewRemaining(flowName) === 0;
    }

    public isRowExpandable(entityType: string, item: ImportResultItem): boolean {
        if (entityType !== 'Flow') return false;
        return this.hasReviewNodes(item.name) || this.hasExpandableFields(entityType, item);
    }

    public getEntityTypeLabel(entityType: string): string {
        const labelMap: { [key: string]: string } = {
            Agent: 'Agent',
            EmbeddingConfig: 'Embedding Config',
            EmbeddingModel: 'Embedding Model',
            EmbeddingModelTag: 'Embedding Model Tag',
            Flow: 'Flow',
            LLMConfig: 'LLM Config',
            LLMModel: 'LLM Model',
            LLMModelTag: 'LLM Model Tag',
            MCPTool: 'MCP Tool',
            Project: 'Project',
            PythonCodeTool: 'Python Code Tool',
            RealtimeConfig: 'Realtime Config',
            RealtimeModel: 'Realtime Model',
            RealtimeTranscriptionConfig: 'Realtime Transcription Config',
            RealtimeTranscriptionModel: 'Realtime Transcription Model',
            Tool: 'Tool',
        };

        return labelMap[entityType] || entityType;
    }

    public isToolEntityType(entityType: string): boolean {
        return entityType === 'Tool';
    }

    public getIconColorForEntityType(entityType: string): string {
        if (entityType === 'Tool') return 'var(--color-text-primary)';
        const grayTypes = ['Flow', 'Project'];

        return grayTypes.includes(entityType) ? 'var(--gray-400)' : 'var(--accent-color)';
    }

    public getGroupIconColor(entityType: string): string {
        const lightTypes = ['Tool', 'Flow'];
        return lightTypes.includes(entityType)
            ? 'var(--color-text-primary)'
            : this.getIconColorForEntityType(entityType);
    }

    public getIconForEntityType(entityType: string): string {
        return ENTITY_ICONS[entityType] || DEFAULT_ENTITY_ICON;
    }

    public isInlineSvgIcon(entityType: string): boolean {
        const iconValue = this.getIconForEntityType(entityType);
        return iconValue.startsWith('<svg');
    }

    public getInlineSvgIcon(entityType: string): SafeHtml {
        const iconValue = this.getIconForEntityType(entityType);
        return this.sanitizer.bypassSecurityTrustHtml(iconValue);
    }

    public getEntityTypeCount(entityType: string): number {
        return this.getEntityTypeResult(entityType)?.total || 0;
    }

    public getEntityTypeResult(entityType: string): EntityTypeResult | undefined {
        if (entityType === 'Tool') return this.mergedToolResult();
        return this.importResult[entityType];
    }

    private mergedToolResult(): EntityTypeResult | undefined {
        const python = this.importResult['PythonCodeTool'];
        const mcp = this.importResult['MCPTool'];
        if (!python && !mcp) return undefined;

        return {
            total: (python?.total ?? 0) + (mcp?.total ?? 0),
            created: {
                count: (python?.created.count ?? 0) + (mcp?.created.count ?? 0),
                items: [...(python?.created.items ?? []), ...(mcp?.created.items ?? [])],
            },
            reused: {
                count: (python?.reused.count ?? 0) + (mcp?.reused.count ?? 0),
                items: [...(python?.reused.items ?? []), ...(mcp?.reused.items ?? [])],
            },
        };
    }

    public ngAfterViewInit(): void {
        this.onSummaryScroll();

        const el = this.summaryListRef?.nativeElement;
        if (!el) return;

        const observer = new ResizeObserver(() => {
            this.onSummaryScroll();
        });
        observer.observe(el);

        this.destroyRef.onDestroy(() => observer.disconnect());
    }

    public onSummaryScroll(): void {
        const el = this.summaryListRef?.nativeElement;
        if (!el) return;
        this._scrollLeft.set(el.scrollLeft);
        this._scrollWidth.set(el.scrollWidth);
        this._clientWidth.set(el.clientWidth);
    }

    public scrollSummary(direction: -1 | 1): void {
        const el = this.summaryListRef?.nativeElement;
        if (!el) return;
        el.scrollBy({ left: direction * this.SCROLL_STEP, behavior: 'smooth' });
    }

    public scrollToEntityGroup(entityType: string): void {
        const index = this.visibleEntityTypes().indexOf(entityType);
        if (index === -1) return;

        const groupEl = this.entityGroupRefs?.toArray()[index]?.nativeElement;
        if (!groupEl) return;

        groupEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        this._triggerHighlight(entityType);
    }

    private _triggerHighlight(entityType: string): void {
        if (this._highlightTimeout) clearTimeout(this._highlightTimeout);
        this.highlightedGroup.set(entityType);
        this._highlightTimeout = setTimeout(() => this.highlightedGroup.set(null), 1500);
    }

    private _itemKey(entityType: string, status: string, id: number | string): string {
        return `${entityType}__${status}__${id}`;
    }

    public toggleItem(entityType: string, status: string, id: number | string): void {
        const key = this._itemKey(entityType, status, id);
        const current = this.expandedItems();
        const next = new Set(current);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.expandedItems.set(next);
    }

    public isItemExpanded(entityType: string, status: string, id: number | string): boolean {
        return this.expandedItems().has(this._itemKey(entityType, status, id));
    }

    private readonly ENTITY_DISPLAY_FIELDS: Record<string, { field: string; label: string }[]> = {
        Flow: [
            { field: 'description', label: 'Description' },
            { field: 'time_to_live', label: 'TTL (s)' },
            { field: 'persistent_variables', label: 'Persistent Vars' },
        ],
        Project: [
            { field: 'description', label: 'Description' },
            { field: 'process', label: 'Process' },
            { field: 'memory', label: 'Memory' },
            { field: 'max_rpm', label: 'Max RPM' },
            { field: 'planning', label: 'Planning' },
        ],
        Agent: [
            { field: 'goal', label: 'Goal' },
            { field: 'backstory', label: 'Backstory' },
        ],
        LLMModel: [
            { field: 'provider_name', label: 'Provider' },
            { field: 'predefined', label: 'Predefined' },
            { field: 'is_custom', label: 'Custom' },
        ],
        LLMConfig: [
            { field: 'temperature', label: 'Temperature' },
            { field: 'max_tokens', label: 'Max Tokens' },
            { field: 'timeout', label: 'Timeout (s)' },
        ],
        PythonCodeTool: [{ field: 'description', label: 'Description' }],
        MCPTool: [{ field: 'description', label: 'Description' }],
        Tool: [{ field: 'description', label: 'Description' }],
        RealtimeModel: [
            { field: 'provider_name', label: 'Provider' },
            { field: 'is_custom', label: 'Custom' },
        ],
        RealtimeConfig: [{ field: 'custom_name', label: 'Config Name' }],
    };

    public getEntityFields(entityType: string, item: ImportResultItem): { label: string; value: string }[] {
        const config = this.ENTITY_DISPLAY_FIELDS[entityType] ?? [];
        return config
            .map(({ field, label }) => {
                const val = (item as unknown as Record<string, unknown>)[field];
                if (val === null || val === undefined || val === '') return null;
                const value = typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val);
                return { label, value };
            })
            .filter((e): e is { label: string; value: string } => e !== null);
    }

    public hasExpandableFields(entityType: string, item: ImportResultItem): boolean {
        return this.getEntityFields(entityType, item).length > 0;
    }

    public onCancel(): void {
        this.dialogRef.close({ action: 'cancel' });
    }

    public readonly isReviewComplete = computed(() => {
        const reviewed = this.reviewedNodeKeys();
        return this.reviewableEntries.every((entry) => reviewed.has(entry.fieldKey));
    });

    public readonly isImporting = signal(false);

    public onImport(): void {
        if (!this.isReviewComplete() || this.isImporting()) return;

        this.isImporting.set(true);
        this.data.importFn().subscribe({
            next: (result) => {
                this.isImporting.set(false);
                this.dialogRef.close({ action: 'imported', result });
            },
            error: (error) => {
                this.isImporting.set(false);
                const message =
                    error?.error?.detail ||
                    error?.error?.message ||
                    'Failed to import. Please check the file and try again.';
                this.toastService.error(message);
            },
        });
    }
}
