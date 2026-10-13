import { Dialog } from '@angular/cdk/dialog';
import { CdkDrag, CdkDragDrop, CdkDragHandle, CdkDropList, moveItemInArray } from '@angular/cdk/drag-drop';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    linkedSignal,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ConfirmationDialogService } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml } from '@shared/utils';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../services/notifications';
import { StorageItem } from '../../../../../../files/models/storage.models';
import { StorageApiService } from '../../../../../../files/services/storage-api.service';
import {
    ExtractTextFromStorageDialogComponent,
    ExtractTextFromStorageDialogResult,
} from '../../../../../components/extract-text-from-storage-dialog/extract-text-from-storage-dialog.component';
import { AgentInstruction } from '../../../../../models/agent-definition.model';
import {
    DUPLICATE_INSTRUCTION_NAME_MESSAGE,
    INSTRUCTIONS_ACCEPT_ATTR,
    isInstructionNameTaken,
    nextDefaultInstructionName,
    readFileAsText,
    uniqueInstructionName,
} from '../../../../../utils/instructions-file.utils';

/**
 * The agent's ordered instruction files: open, rename, delete, drag-reorder, create and
 * import. Owns no persistence — every change emits the full next list; the parent saves it.
 */
@Component({
    selector: 'app-agent-instructions-list',
    imports: [
        AppSvgIconComponent,
        CdkDrag,
        CdkDragHandle,
        CdkDropList,
        HasPermissionDirective,
        MatTooltipModule,
        ReactiveFormsModule,
    ],
    templateUrl: './agent-instructions-list.component.html',
    styleUrls: ['./agent-instructions-list.component.scss'],
})
export class AgentInstructionsListComponent {
    readonly instructions = input<AgentInstruction[]>([]);
    /** Bumped by the parent when a save fails — drops the optimistic list back to `instructions`. */
    readonly saveErrorTick = input<number>(0);
    readonly serverError = input<string | null>(null);
    readonly isCreating = input<boolean>(false);
    readonly readOnly = input<boolean>(false);

    readonly instructionListChange = output<AgentInstruction[]>();
    readonly openInstruction = output<{ index: number; edit: boolean }>();

    private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');

    // Optimistic copy: a drop / rename shows at once instead of snapping back until the PATCH returns.
    protected readonly rows = linkedSignal<{ list: AgentInstruction[]; tick: number }, AgentInstruction[]>({
        source: () => ({ list: this.instructions(), tick: this.saveErrorTick() }),
        computation: (source) => source.list,
    });
    protected readonly renamingIndex = signal<number | null>(null);
    /** A just-created instruction opens in Edit once its name is confirmed. */
    private openAfterRenameIndex: number | null = null;
    protected readonly renameError = signal<string | null>(null);
    protected readonly displayedError = computed<string | null>(() => this.renameError() ?? this.serverError());
    protected readonly editable = computed<boolean>(
        () => !this.readOnly() && this.permissionService.can(ResourceCode.Agents, ActionCode.Update)
    );

    protected readonly acceptAttr = INSTRUCTIONS_ACCEPT_ATTR;
    protected readonly renameControl = new FormControl<string>('', { nonNullable: true });
    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly confirm = inject(ConfirmationDialogService);
    private readonly storageApiService = inject(StorageApiService);
    private readonly toast = inject(ToastService);
    private readonly permissionService = inject(PermissionsService);

    constructor() {
        // The rename input appears with its whole text selected, ready to type over.
        effect(() => {
            const element = this.renameInput()?.nativeElement;
            if (!element) return;
            element.focus();
            element.select();
        });
    }

    onDrop(event: CdkDragDrop<AgentInstruction[]>): void {
        if (event.previousIndex === event.currentIndex) return;
        const list = [...this.rows()];
        moveItemInArray(list, event.previousIndex, event.currentIndex);
        this.commit(list);
    }

    startRename(index: number): void {
        const instruction = this.rows()[index];
        if (!instruction || !this.editable()) return;
        this.renameControl.setValue(instruction.name);
        this.renameError.set(null);
        this.renamingIndex.set(index);
    }

    /** Enter / blur. Empty or unchanged → revert; duplicate → keep the input open with the error. */
    commitRename(index: number): void {
        if (this.renamingIndex() !== index) return;
        const list = this.rows();
        const current = list[index];
        const name = this.renameControl.value.trim();
        if (isInstructionNameTaken(name, list, index)) {
            this.renameError.set(DUPLICATE_INSTRUCTION_NAME_MESSAGE);
            return;
        }
        const openAfterRename = this.openAfterRenameIndex === index;
        this.cancelRename();
        if (current && name && name !== current.name) {
            this.commit(list.map((instruction, i) => (i === index ? { ...instruction, name } : instruction)));
        }
        if (current && openAfterRename) this.openInstruction.emit({ index, edit: true });
    }

    cancelRename(): void {
        this.openAfterRenameIndex = null;
        this.renamingIndex.set(null);
        this.renameError.set(null);
    }

    onDelete(index: number): void {
        const instruction = this.rows()[index];
        if (!instruction) return;
        this.cancelRename();
        const remove = (): void => this.commit(this.rows().filter((_, i) => i !== index));
        if (!instruction.content.trim()) {
            remove();
            return;
        }
        this.confirm
            .confirm({
                title: 'Delete instruction?',
                message: `"${escapeHtml(instruction.name)}" and its content will be removed from this agent.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) remove();
            });
    }

    onCreateMarkdown(): void {
        const list = this.rows();
        this.commit([...list, { name: nextDefaultInstructionName(list), content: '' }]);
        // While drafting, the parent creates the agent and opens the new doc instead.
        if (this.isCreating()) return;
        this.startRename(list.length);
        this.openAfterRenameIndex = list.length;
    }

    /** "Extract Text from PC": open the native file picker (no upload). */
    onExtractFromPc(fileInput: HTMLInputElement): void {
        fileInput.click();
    }

    onPcFileSelected(event: Event): void {
        const fileInput = event.target as HTMLInputElement;
        const file = fileInput.files?.[0];
        fileInput.value = ''; // allow re-picking the same file
        if (!file) return;
        readFileAsText(file)
            .then((text) => this.appendExtracted(file.name, text))
            .catch(() => this.toast.error(`Failed to read "${file.name}"`));
    }

    /** "Extract Text from Storage": pick a text file from storage and read it. */
    onExtractFromStorage(): void {
        this.dialog
            .open<ExtractTextFromStorageDialogResult | undefined>(ExtractTextFromStorageDialogComponent)
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result) this.readStorageFile(result.item);
            });
    }

    private readStorageFile(item: StorageItem): void {
        this.storageApiService
            .downloadBlob(item.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) =>
                    readFileAsText(blob)
                        .then((text) => this.appendExtracted(item.name, text))
                        .catch(() => this.toast.error(`Failed to read "${item.name}"`)),
                error: () => this.toast.error(`Failed to load "${item.name}" from storage`),
            });
    }

    private appendExtracted(fileName: string, content: string): void {
        if (this.isCreating()) {
            this.toast.info('Save the agent before importing instructions');
            return;
        }
        const list = this.rows();
        this.commit([...list, { name: uniqueInstructionName(fileName, list), content }]);
    }

    private commit(list: AgentInstruction[]): void {
        this.rows.set(list);
        this.instructionListChange.emit(list);
    }
}
