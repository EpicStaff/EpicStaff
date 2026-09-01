import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, HostListener, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    CDT_SECTION_COLOR_OPTIONS,
    CDT_SECTION_DEFAULT_COLOR,
    CdtSectionColorOption,
    normalizeCdtSectionColor,
} from '../../../../core/models/cdt-section.model';

export interface CdtGroupDialogData {
    mode: 'create' | 'edit';
    name?: string;
    color?: string;
}

export type CdtGroupDialogResult = { name: string; color: string } | undefined;

@Component({
    selector: 'app-cdt-group-dialog',
    imports: [CommonModule, DialogModule, FormsModule, AppSvgIconComponent],
    templateUrl: './cdt-group-dialog.component.html',
    styleUrls: ['./cdt-group-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtGroupDialogComponent {
    private readonly dialogRef = inject<DialogRef<CdtGroupDialogResult>>(DialogRef);
    public readonly data = inject<CdtGroupDialogData>(DIALOG_DATA);

    public readonly name = signal<string>(this.data.mode === 'edit' ? (this.data.name ?? '') : '');
    public readonly selectedColor = signal<string>(
        this.data.mode === 'edit' ? normalizeCdtSectionColor(this.data.color) : CDT_SECTION_DEFAULT_COLOR
    );

    public readonly isSaveDisabled = computed(() => this.name().trim().length === 0);

    public readonly title = this.data.mode === 'edit' ? 'Edit Group' : 'Create Group';
    public readonly colorOptions: readonly CdtSectionColorOption[] = CDT_SECTION_COLOR_OPTIONS;

    @HostListener('keydown.escape')
    public onEscape(): void {
        this.cancel();
    }

    public onNameKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Enter') {
            return;
        }
        event.preventDefault();
        this.save();
    }

    public selectColor(hex: string): void {
        this.selectedColor.set(hex);
    }

    public isColorSelected(option: CdtSectionColorOption): boolean {
        return option.hex.toLowerCase() === this.selectedColor().toLowerCase();
    }

    public save(): void {
        if (this.isSaveDisabled()) {
            return;
        }
        this.dialogRef.close({ name: this.name().trim(), color: this.selectedColor() });
    }

    public cancel(): void {
        this.dialogRef.close(undefined);
    }
}
