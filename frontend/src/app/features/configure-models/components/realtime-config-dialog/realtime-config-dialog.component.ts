import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, IconButtonComponent } from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';

import {
    RealtimeConfig,
    RealtimeConfigFormComponent,
    RealtimeProvider,
} from '../realtime-config-form/realtime-config-form.component';

/** Edits `config`; its provider stays fixed. New voice configs are created from "Add Configuration". */
export interface RealtimeConfigDialogData {
    provider: RealtimeProvider;
    config: RealtimeConfig;
}

@Component({
    selector: 'app-realtime-config-dialog',
    templateUrl: './realtime-config-dialog.component.html',
    styleUrls: ['./realtime-config-dialog.component.scss'],
    imports: [ButtonComponent, IconButtonComponent, EnterSubmitDirective, RealtimeConfigFormComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RealtimeConfigDialogComponent implements OnInit {
    private readonly form = viewChild(RealtimeConfigFormComponent);

    protected readonly isSaving = computed(() => this.form()?.isSubmitting() ?? false);
    protected readonly saveLabel = computed(() => (this.isSaving() ? 'Saving…' : 'Save Changes'));

    protected readonly data = inject<RealtimeConfigDialogData>(DIALOG_DATA);

    private readonly dialogRef = inject(DialogRef);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    onSave(): void {
        this.form()?.submit();
    }

    onSaved(): void {
        this.dialogRef.close(true);
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
