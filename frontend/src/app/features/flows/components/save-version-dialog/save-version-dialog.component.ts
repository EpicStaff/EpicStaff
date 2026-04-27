import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Subscription } from 'rxjs';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';

export interface SaveVersionDialogResult {
    name: string;
    description: string;
}

@Component({
    selector: 'app-save-version-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, AppSvgIconComponent],
    templateUrl: './save-version-dialog.component.html',
    styleUrls: ['./save-version-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SaveVersionDialogComponent implements OnInit, OnDestroy {
    public form = new FormGroup({
        name: new FormControl('', [Validators.required, Validators.maxLength(255)]),
        description: new FormControl(''),
    });

    private keydownSubscription?: Subscription;

    constructor(
        public dialogRef: DialogRef<SaveVersionDialogResult>,
        @Inject(DIALOG_DATA) public data: unknown
    ) {}

    ngOnInit(): void {
        this.keydownSubscription = this.dialogRef.keydownEvents.subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                event.stopPropagation();
                this.onSubmit();
            }
        });
    }

    ngOnDestroy(): void {
        this.keydownSubscription?.unsubscribe();
    }

    public onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        this.dialogRef.close({
            name: this.form.value.name!.trim(),
            description: (this.form.value.description ?? '').trim(),
        });
    }

    public onCancel(): void {
        this.dialogRef.close();
    }
}
