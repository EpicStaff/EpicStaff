import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, Inject, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';

import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';

export interface AdvancedTaskSettingsData {
    config: Record<string, unknown> | null;
    output_model: Record<string, unknown> | null;
    task_context_list: number[];
    taskName: string;
    taskId: number | string | null;
    availableTasks?: { id: number; order: number | null; name?: string }[];
    _saveAfterClose?: boolean;
}

@Component({
    selector: 'app-advanced-task-settings-dialog',
    standalone: true,
    imports: [
        NgIf,
        NgFor,
        NgClass,
        FormsModule,
        MatSlideToggleModule,
        JsonEditorComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './advanced-task-settings-dialog.component.html',
    styleUrls: ['./advanced-task-settings-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdvancedTaskSettingsDialogComponent implements OnInit {
    public taskData: AdvancedTaskSettingsData;
    public jsonConfig = signal<string>('{}');
    public isJsonValid = signal<boolean>(true);
    public selectedTaskIds = signal<number[]>([]);
    public readonly availableTasks: { id: number; order: number | null; name?: string }[];
    public useOutputModel = signal<boolean>(false);
    private readonly destroyRef = inject(DestroyRef);
    private _closeWithPageSave = false;

    constructor(
        public dialogRef: DialogRef<AdvancedTaskSettingsData>,
        @Inject(DIALOG_DATA) public data: AdvancedTaskSettingsData
    ) {
        this.taskData = {
            ...data,
            config: null,
            task_context_list: data.task_context_list || [],
            output_model: data.output_model || null,
            taskId: data.taskId,
        };

        this.availableTasks = [...(data.availableTasks || [])].sort((a, b) => {
            if (a.order === null && b.order === null) {
                return 0;
            }
            if (a.order === null) {
                return 1;
            }
            if (b.order === null) {
                return -1;
            }
            return a.order - b.order;
        });

        const initialSelectedIds = Array.isArray(data.task_context_list)
            ? [...data.task_context_list].map((id) => (typeof id === 'string' ? parseInt(id, 10) : id))
            : [];

        this.selectedTaskIds.set(initialSelectedIds);

        // Initialize useOutputModel based on whether output_model exists
        this.useOutputModel.set(this.taskData.output_model !== null && this.taskData.output_model !== undefined);

        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.requestClose();
        });

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                this.requestClose();
            }
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                event.stopPropagation();
                this._closeWithPageSave = true;
                this.requestClose();
            }
        });
    }

    public ngOnInit(): void {
        if (this.taskData.output_model) {
            try {
                const outputModel = this.taskData.output_model;
                const schemaString = JSON.stringify(outputModel, null, 2);
                this.jsonConfig.set(this.stripTypeAndTitle(schemaString));
            } catch {
                this.jsonConfig.set(this.getDefaultJsonSchema());
            }
        } else {
            this.jsonConfig.set(this.getDefaultJsonSchema());
        }
    }

    private getDefaultJsonSchema(): string {
        const defaultSchema = {
            properties: {},
            required: [],
        };
        return JSON.stringify(defaultSchema, null, 2);
    }

    private stripTypeAndTitle(schemaString: string): string {
        try {
            const schema = JSON.parse(schemaString);
            const { type: _type, title: _title, ...rest } = schema;
            void _type;
            void _title;
            return JSON.stringify(rest, null, 2);
        } catch {
            return schemaString;
        }
    }

    public onJsonValidChange(isValid: boolean): void {
        this.isJsonValid.set(isValid);
    }

    public resetToDefault(): void {
        this.jsonConfig.set(this.getDefaultJsonSchema());
    }

    public toggleTaskSelection(taskId: number): void {
        const currentSelection = this.selectedTaskIds();
        const index = currentSelection.indexOf(taskId);

        if (index === -1) {
            // Task is not selected, add it
            this.selectedTaskIds.set([...currentSelection, taskId]);
        } else {
            // Task is already selected, remove it
            const updatedSelection = [...currentSelection];
            updatedSelection.splice(index, 1);
            this.selectedTaskIds.set(updatedSelection);
        }
    }

    public isTaskSelected(taskId: number): boolean {
        return this.selectedTaskIds().includes(taskId);
    }

    // Helper to format order display
    public formatOrder(order: number | null): string {
        return order === null ? 'null' : `${order}`;
    }

    public tryProcessOutputModel(jsonString: string): Record<string, unknown> | null {
        if (!jsonString) return null;

        try {
            const parsedJson = JSON.parse(jsonString);

            const hasProperties = parsedJson.properties && Object.keys(parsedJson.properties).length > 0;

            if (!hasProperties) {
                return null;
            }

            return {
                type: 'object',
                title: 'TaskOutputModel',
                ...parsedJson,
            };
        } catch (e) {
            console.error('Error processing output model:', e);
            return null;
        }
    }

    public save(): void {
        if (this.useOutputModel() && !this.isJsonValid()) {
            return;
        }

        try {
            let outputModel = null;

            if (this.useOutputModel()) {
                outputModel = this.tryProcessOutputModel(this.jsonConfig());
            }

            const result = {
                ...this.taskData,
                config: null,
                output_model: outputModel,
                task_context_list: this.selectedTaskIds(),
                _saveAfterClose: this._closeWithPageSave,
            };
            this._closeWithPageSave = false;
            this.dialogRef.close(result);
        } catch {
            this.isJsonValid.set(false);
        }
    }

    public requestClose(): void {
        this.save();
    }
}
