import { CdkDragDrop, DragDropModule, moveItemInArray } from '@angular/cdk/drag-drop';
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal, ViewChild } from '@angular/core';
import { AppSvgIconComponent, MultiSelectComponent, SelectItem } from '@shared/components';

import { AgentNodeTaskUi } from '../../../../../pages/flows-page/components/flow-visual-programming/models/agent-node.model';
import { ToastService } from '../../../../../services/notifications';
import { isValidOutputSchema } from '../../../../utils/validation/output-schema.validator';
import { VariableHighlightTextareaComponent } from '../../shared/variable-highlight-textarea/variable-highlight-textarea.component';

interface ContextRef {
    id?: number;
    tempId?: string;
}

interface ResolvedTaskRef extends AgentNodeTaskUi {
    order: number;
}

@Component({
    selector: 'app-agent-tasks-table',
    imports: [DragDropModule, AppSvgIconComponent, MultiSelectComponent, VariableHighlightTextareaComponent],
    templateUrl: './agent-tasks-table.component.html',
    styleUrls: ['./agent-tasks-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentTasksTableComponent {
    public readonly tasks = input.required<AgentNodeTaskUi[]>();
    public readonly activeColor = input<string>('var(--accent-color)');
    public readonly selectedCell = input<{ taskIndex: number; field: 'instructions' | 'schema' } | null>(null);
    public readonly variableNames = input<string[]>([]);

    public readonly showValidation = input<boolean>(false);
    public readonly tasksChange = output<AgentNodeTaskUi[]>();
    public readonly cellSelect = output<{ taskIndex: number; field: 'instructions' | 'schema' }>();

    public readonly schemaDrafts = signal<Record<string, string>>({});
    public readonly invalidSchemaIds = signal<Set<string>>(new Set());

    public readonly contextPopupRowIndex = signal<number | null>(null);

    public readonly contextCandidates = computed<ResolvedTaskRef[]>(() => {
        const rowIndex = this.contextPopupRowIndex();
        if (rowIndex === null) return [];
        return this.tasks()
            .slice(0, rowIndex)
            .map((t, idx) => ({ ...t, order: idx + 1 }));
    });

    public readonly contextItems = computed<SelectItem[]>(() =>
        this.contextCandidates().map((c) => ({ name: c.name || 'Untitled', value: c.id ?? c.tempId }))
    );

    public readonly contextSelectedValues = computed<unknown[]>(() => {
        const rowIndex = this.contextPopupRowIndex();
        if (rowIndex === null) return [];
        const task = this.tasks()[rowIndex];
        return (task?.contextRefs ?? []).map((ref) => ref.id ?? ref.tempId);
    });

    @ViewChild('contextMultiSelect') private contextMultiSelect!: MultiSelectComponent;

    private readonly toastService = inject(ToastService);

    trackByTempId(_index: number, task: AgentNodeTaskUi): string {
        return task.tempId;
    }

    onNameInput(index: number, event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.updateTask(index, { name: value });
    }

    onInstructionsInput(index: number, value: string): void {
        this.updateTask(index, { instructions: value });
    }

    getSchemaText(task: AgentNodeTaskUi): string {
        const draft = this.schemaDrafts()[task.tempId];
        if (draft !== undefined) return draft;
        return this.stringifySchema(task.output_schema);
    }

    onSchemaInput(tempId: string, event: Event): void {
        const value = (event.target as HTMLTextAreaElement).value;
        this.schemaDrafts.update((drafts) => ({ ...drafts, [tempId]: value }));
    }

    onSchemaBlur(index: number, task: AgentNodeTaskUi): void {
        const draft = this.schemaDrafts()[task.tempId];
        if (draft === undefined) return;

        const trimmed = draft.trim();
        try {
            const parsed = trimmed === '' ? {} : JSON.parse(trimmed);
            this.setInvalid(task.tempId, !isValidOutputSchema(parsed));
            this.schemaDrafts.update((drafts) =>
                Object.fromEntries(Object.entries(drafts).filter(([key]) => key !== task.tempId))
            );
            this.updateTask(index, { output_schema: parsed, output_schema_invalid: false });
        } catch {
            this.setInvalid(task.tempId, true);
            this.updateTask(index, { output_schema_invalid: true });
        }
    }

    private setInvalid(tempId: string, invalid: boolean): void {
        this.invalidSchemaIds.update((set) => {
            const has = set.has(tempId);
            if (has === invalid) return set;
            const next = new Set(set);
            if (invalid) {
                next.add(tempId);
            } else {
                next.delete(tempId);
            }
            return next;
        });
    }

    onExpandCell(taskIndex: number, field: 'instructions' | 'schema', event: MouseEvent): void {
        event.stopPropagation();
        this.cellSelect.emit({ taskIndex, field });
    }

    isCellSelected(taskIndex: number, field: 'instructions' | 'schema'): boolean {
        const sel = this.selectedCell();
        return !!sel && sel.taskIndex === taskIndex && sel.field === field;
    }

    isNameInvalid(task: AgentNodeTaskUi): boolean {
        return this.showValidation() && !(task.name ?? '').trim();
    }

    isInstructionsInvalid(task: AgentNodeTaskUi): boolean {
        return this.showValidation() && !(task.instructions ?? '').trim();
    }

    getResolvedContext(task: AgentNodeTaskUi): ResolvedTaskRef[] {
        const all = this.tasks();
        const resolved: ResolvedTaskRef[] = [];
        for (const ref of task.contextRefs ?? []) {
            const idx = all.findIndex((t) => this.refMatchesTask(ref, t));
            if (idx !== -1) {
                resolved.push({ ...all[idx], order: idx + 1 });
            }
        }
        return resolved;
    }

    removeTask(index: number): void {
        const removed = this.tasks()[index];
        const remaining = this.tasks().filter((_, i) => i !== index);
        const cleaned = remaining.map((t) => ({
            ...t,
            contextRefs: (t.contextRefs ?? []).filter((ref) => !this.refMatchesTask(ref, removed)),
        }));
        this.emit(cleaned);
    }

    clearAll(): void {
        this.emit([]);
    }

    onDrop(event: CdkDragDrop<AgentNodeTaskUi[]>): void {
        if (event.previousIndex === event.currentIndex) return;

        const reordered = [...this.tasks()];
        moveItemInArray(reordered, event.previousIndex, event.currentIndex);

        const affectedNames = new Set<string>();
        const stripped = reordered.map((task, newIndex) => {
            const keptRefs = (task.contextRefs ?? []).filter((ref) => {
                const targetIndex = reordered.findIndex((t) => this.refMatchesTask(ref, t));
                const isBackward = targetIndex !== -1 && targetIndex < newIndex;
                if (!isBackward) {
                    affectedNames.add(task.name?.trim() || `Task ${newIndex + 1}`);
                }
                return isBackward;
            });
            return keptRefs.length === (task.contextRefs ?? []).length ? task : { ...task, contextRefs: keptRefs };
        });

        if (affectedNames.size > 0) {
            this.toastService.warning(
                `Removed forward-pointing task context on: ${Array.from(affectedNames).join(', ')}`,
                6000,
                'bottom-right'
            );
        }

        this.emit(stripped);
    }

    openContextPopup(rowIndex: number, event: MouseEvent): void {
        event.stopPropagation();
        this.contextPopupRowIndex.set(rowIndex);
        const task = this.tasks()[rowIndex];
        const seedValues = (task.contextRefs ?? []).map((ref) => ref.id ?? ref.tempId);
        this.contextMultiSelect.openAt(event.currentTarget as HTMLElement, seedValues);
    }

    onContextSelectionChange(values: unknown[]): void {
        const rowIndex = this.contextPopupRowIndex();
        if (rowIndex === null) return;
        const tasks = this.tasks();
        const refs: ContextRef[] = values
            .map((value): ContextRef => (typeof value === 'number' ? { id: value } : { tempId: value as string }))
            .filter((ref) => tasks.some((t) => this.refMatchesTask(ref, t)));
        this.updateTask(rowIndex, { contextRefs: refs });
    }

    private refMatchesTask(ref: ContextRef, task: AgentNodeTaskUi): boolean {
        if (ref.id != null && task.id != null) return ref.id === task.id;
        if (ref.tempId != null) return ref.tempId === task.tempId;
        return false;
    }

    private stringifySchema(schema: Record<string, unknown> | null | undefined): string {
        if (!schema || Object.keys(schema).length === 0) return '';
        try {
            return JSON.stringify(schema, null, 2);
        } catch {
            return '';
        }
    }

    private updateTask(index: number, patch: Partial<AgentNodeTaskUi>): void {
        const next = this.tasks().map((t, i) => (i === index ? { ...t, ...patch } : t));
        this.emit(next);
    }

    private emit(tasks: AgentNodeTaskUi[]): void {
        this.tasksChange.emit(tasks);
    }
}
