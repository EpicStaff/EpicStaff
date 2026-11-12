import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, LoadingSpinnerComponent } from '@shared/components';

import { GraphTableData } from '../../models/graph-visualization.model';
import { GraphRagService } from '../../services/graph-rag.service';

interface TableDefinition {
    name: string;
    label: string;
    columns: ReadonlyArray<{ key: string; label: string }>;
}

@Component({
    selector: 'app-graph-rag-data-tables',
    templateUrl: './graph-rag-data-tables.component.html',
    styleUrls: ['./graph-rag-data-tables.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [ButtonComponent, LoadingSpinnerComponent],
})
export class GraphRagDataTablesComponent implements OnInit {
    // 1. Inputs
    readonly ragId = input.required<number>();

    // 3. Signals & Computed
    readonly activeTable = signal<TableDefinition>(TABLES[0]);
    readonly viewState = signal<'idle' | 'loading' | 'ready' | 'empty' | 'error'>('idle');
    readonly errorMessage = signal('');
    readonly rows = signal<Record<string, unknown>[]>([]);
    readonly total = signal(0);
    readonly page = signal(1);
    readonly pageSize = signal(10);
    readonly totalPages = computed(() => Math.ceil(this.total() / this.pageSize()) || 1);

    // 5. Public template-bound properties
    readonly tables = TABLES;

    // 6. Private fields
    private readonly graphRagService = inject(GraphRagService);
    private readonly destroyRef = inject(DestroyRef);

    // 8. Lifecycle hooks
    ngOnInit(): void {
        this.loadTable();
    }

    // 9. Public methods
    onSelectTable(table: TableDefinition): void {
        this.activeTable.set(table);
        this.page.set(1);
        this.loadTable();
    }

    onPageChange(newPage: number): void {
        if (newPage < 1 || newPage > this.totalPages()) return;
        this.page.set(newPage);
        this.loadTable();
    }

    // 10. Private methods
    private loadTable(): void {
        this.viewState.set('loading');
        const table = this.activeTable();
        this.graphRagService
            .getTableData(this.ragId(), table.name, this.page(), this.pageSize())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (data: GraphTableData) => {
                    this.rows.set(data.rows);
                    this.total.set(data.total);
                    this.viewState.set(data.total === 0 ? 'empty' : 'ready');
                },
                error: () => {
                    this.viewState.set('error');
                    this.errorMessage.set('Failed to load table data');
                },
            });
    }
}

const TABLES: ReadonlyArray<TableDefinition> = [
    {
        name: 'entities',
        label: 'Entities',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'title', label: 'Title' },
            { key: 'type', label: 'Type' },
            { key: 'description', label: 'Description' },
            { key: 'degree', label: 'Degree' },
        ],
    },
    {
        name: 'relationships',
        label: 'Relationships',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'source', label: 'Source' },
            { key: 'target', label: 'Target' },
            { key: 'description', label: 'Description' },
            { key: 'weight', label: 'Weight' },
        ],
    },
    {
        name: 'documents',
        label: 'Documents',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'human_readable_id', label: 'Human Readable ID' },
            { key: 'title', label: 'Title' },
        ],
    },
    {
        name: 'text_units',
        label: 'Text Units',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'text', label: 'Text' },
            { key: 'n_tokens', label: 'Tokens' },
        ],
    },
    {
        name: 'communities',
        label: 'Communities',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'title', label: 'Title' },
            { key: 'level', label: 'Level' },
            { key: 'size', label: 'Size' },
        ],
    },
    {
        name: 'community_reports',
        label: 'Community Reports',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'title', label: 'Title' },
            { key: 'summary', label: 'Summary' },
        ],
    },
    {
        name: 'covariates',
        label: 'Covariates',
        columns: [
            { key: 'id', label: 'ID' },
            { key: 'subject_id', label: 'Subject ID' },
            { key: 'subject_type', label: 'Subject Type' },
            { key: 'covariate_type', label: 'Covariate Type' },
            { key: 'description', label: 'Description' },
        ],
    },
];
