import { animate, state, style, transition, trigger } from '@angular/animations';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
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
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Router } from '@angular/router';

import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { DEFAULT_ENTITY_ICON, ENTITY_ICONS } from '../../../../shared/constants/entity-icons.constants';
import {
    EntityTypeResult,
    ImportResult,
    ImportResultDialogData,
    ImportResultItem,
} from '../../models/import-result.model';

@Component({
    selector: 'app-import-result-dialog',
    standalone: true,
    imports: [CommonModule, AppIconComponent],
    templateUrl: './import-result-dialog.component.html',
    styleUrls: ['./import-result-dialog.component.scss'],
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('220ms ease')),
        ]),
    ],
})
export class ImportResultDialogComponent implements AfterViewInit {
    private router = inject(Router);
    private sanitizer = inject(DomSanitizer);
    private destroyRef = inject(DestroyRef);

    @ViewChild('summaryList') summaryListRef!: ElementRef<HTMLElement>;
    @ViewChild('entityListsSection') entityListsSectionRef!: ElementRef<HTMLElement>;
    @ViewChildren('entityGroup') entityGroupRefs!: QueryList<ElementRef<HTMLElement>>;

    private readonly SCROLL_STEP = 240;
    private _scrollLeft = signal(0);
    private _scrollWidth = signal(0);
    private _clientWidth = signal(0);

    public canScrollLeft = computed(() => this._scrollLeft() > 0);
    public canScrollRight = computed(() => this._scrollLeft() < this._scrollWidth() - this._clientWidth() - 1);

    public importResult: ImportResult;
    public collapsedGroups = signal<Set<string>>(new Set());
    public expandedItems = signal<Set<string>>(new Set());
    public highlightedGroup = signal<string | null>(null);
    private _highlightTimeout: ReturnType<typeof setTimeout> | null = null;

    private readonly HIDDEN_ENTITY_TYPES = new Set(['LLMModelTag']);

    private readonly ENTITY_TYPE_ORDER = [
        'Flow',
        'Project',
        'Agent',
        'MCPTool',
        'PythonCodeTool',
        'LLMModel',
        'LLMConfig',
        'RealtimeModel',
        'RealtimeConfig',
    ];

    // Computed signals for dynamic UI
    public totalItemsCount = computed(() => {
        let total = 0;
        Object.entries(this.importResult).forEach(([key, result]) => {
            if (result && !this.HIDDEN_ENTITY_TYPES.has(key)) total += result.total;
        });
        return total;
    });

    public totalCreatedCount = computed(() => {
        let total = 0;
        Object.entries(this.importResult).forEach(([key, result]) => {
            if (result && !this.HIDDEN_ENTITY_TYPES.has(key)) total += result.created.count;
        });
        return total;
    });

    public totalReusedCount = computed(() => {
        let total = 0;
        Object.entries(this.importResult).forEach(([key, result]) => {
            if (result && !this.HIDDEN_ENTITY_TYPES.has(key)) total += result.reused.count;
        });
        return total;
    });

    public allCreated = computed(() => this.totalReusedCount() === 0 && this.totalCreatedCount() > 0);
    public allReused = computed(() => this.totalCreatedCount() === 0 && this.totalReusedCount() > 0);

    public entityTypes = computed(() => {
        const keys = Object.keys(this.importResult).filter((k) => !this.HIDDEN_ENTITY_TYPES.has(k));
        return keys.sort((a, b) => {
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

    constructor(
        public dialogRef: DialogRef<void>,
        @Inject(DIALOG_DATA) public data: ImportResultDialogData
    ) {
        this.importResult = data.importResult;
    }

    /**
     * Get display name for entity type (e.g., "GRAPH" -> "Flow")
     */
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
        };

        return labelMap[entityType] || entityType;
    }

    /**
     * Get icon for entity type (e.g., "GRAPH" -> flows icon)
     */
    public getIconColorForEntityType(entityType: string): string {
        if (entityType === 'PythonCodeTool') return '#FFCF3F';
        const grayTypes = ['Flow', 'Project'];

        return grayTypes.includes(entityType) ? 'var(--gray-400)' : 'var(--accent-color)';
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

    /**
     * Get total count for entity type
     */
    public getEntityTypeCount(entityType: string): number {
        return this.importResult[entityType]?.total || 0;
    }

    /**
     * Get entity type result
     */
    public getEntityTypeResult(entityType: string): EntityTypeResult | undefined {
        return this.importResult[entityType];
    }

    /**
     * Get status badge style class
     */
    public getStatusClass(status: 'created' | 'reused'): string {
        return status === 'created' ? 'status-created' : 'status-reused';
    }

    /**
     * Navigate to entity details in a new tab
     */
    public navigateToEntity(entityType: string, id: number | string): void {
        const routeMap: { [key: string]: string } = {
            Flow: '/flows',
            Project: '/projects',
            Agent: '/agents',
        };

        const basePath = routeMap[entityType];
        if (basePath) {
            const urlTree = this.router.createUrlTree([basePath, id]);
            const url = this.router.serializeUrl(urlTree);
            window.open(url, '_blank');
        }
    }

    /**
     * Check if entity has navigable route
     */
    public isNavigable(entityType: string): boolean {
        const navigableTypes = ['Flow', 'Project', 'Agent'];
        return navigableTypes.includes(entityType);
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

        const scrollAndHighlight = () => {
            groupEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
            this._triggerHighlight(entityType);
        };

        // Expand the group if collapsed
        const collapsed = this.collapsedGroups();
        if (collapsed.has(entityType)) {
            const next = new Set(collapsed);
            next.delete(entityType);
            this.collapsedGroups.set(next);
            setTimeout(scrollAndHighlight);
        } else {
            scrollAndHighlight();
        }
    }

    private _triggerHighlight(entityType: string): void {
        if (this._highlightTimeout) clearTimeout(this._highlightTimeout);
        this.highlightedGroup.set(entityType);
        this._highlightTimeout = setTimeout(() => this.highlightedGroup.set(null), 1500);
    }

    public toggleGroup(entityType: string): void {
        const current = this.collapsedGroups();
        const next = new Set(current);
        if (next.has(entityType)) {
            next.delete(entityType);
        } else {
            next.add(entityType);
        }
        this.collapsedGroups.set(next);
    }

    public isGroupCollapsed(entityType: string): boolean {
        return this.collapsedGroups().has(entityType);
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

    /**
     * Close dialog
     */
    public closeDialog(): void {
        this.dialogRef.close();
    }
}
