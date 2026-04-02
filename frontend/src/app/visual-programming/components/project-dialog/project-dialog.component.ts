import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    HostListener,
    Inject,
    inject,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SaveWithIndicatorComponent } from 'src/app/shared/components/save-with-indicator/save-with-indicator.component';
import { UnsavedChangesDialogService } from 'src/app/shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { UnsavedIndicatorComponent } from 'src/app/shared/components/unsaved-indicator/unsaved-indicator.component';

import { OpenProjectPageComponent } from '../../../open-project-page/open-project-page.component';

@Component({
    selector: 'app-project-dialog',
    standalone: true,
    imports: [CommonModule, OpenProjectPageComponent, SaveWithIndicatorComponent, UnsavedIndicatorComponent],
    template: `
        <div class="project-dialog-wrapper">
            <div class="dialog-header">
                <div class="icon-and-title">
                    <i class="ti ti-folder"></i>
                    <span class="title">{{ data.projectName }}</span>
                    <app-unsaved-indicator [show]="openProjectPage?.hasUnsavedChanges ?? false"></app-unsaved-indicator>
                </div>
                <div class="header-actions">
                    <app-save-with-indicator
                        [isSaving]="openProjectPage?.isSaving ?? false"
                        [disabled]="
                            !(openProjectPage?.hasUnsavedChanges ?? false) || (openProjectPage?.isSaving ?? false)
                        "
                        (save)="openProjectPage?.onSaveAll()"
                    ></app-save-with-indicator>
                    <div class="close-action">
                        <span class="esc-label">ESC</span>
                        <i class="ti ti-x close-icon" (click)="tryClose()"></i>
                    </div>
                </div>
            </div>
            <div class="dialog-content">
                <app-open-project-page [showHeader]="true" [inputProjectId]="data.projectId"> </app-open-project-page>
            </div>
        </div>
    `,
    styleUrls: ['./project-dialog.component.scss'],
})
export class ProjectDialogComponent implements AfterViewInit {
    @ViewChild(OpenProjectPageComponent) openProjectPage?: OpenProjectPageComponent;

    dialogRef = inject(DialogRef);
    private cdr = inject(ChangeDetectorRef);
    private unsavedChangesDialog = inject(UnsavedChangesDialogService);
    private destroyRef = inject(DestroyRef);

    constructor(
        @Inject(DIALOG_DATA)
        public data: {
            projectId: number;
            projectName: string;
        }
    ) {}

    ngAfterViewInit(): void {
        queueMicrotask(() => this.cdr.detectChanges());

        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.tryClose());
    }

    public tryClose(): void {
        const page = this.openProjectPage;

        if (!page || !page.hasUnsavedChanges) {
            this.dialogRef.close();
            return;
        }

        this.unsavedChangesDialog
            .confirm({
                title: 'Unsaved Changes',
                message: 'You have unsaved changes in this project. What would you like to do?',
                saveText: 'Save & Leave',
                dontSaveText: "Don't Save & Leave",
                cancelText: 'Cancel',
                type: 'warning',
                onSave: () => page.savePendingForLeave(),
            })
            .subscribe((result) => {
                if (result === 'save') {
                    this.dialogRef.close();
                    return;
                }

                if (result === 'dont-save') {
                    page.discardPendingChanges();
                    this.dialogRef.close();
                    return;
                }
            });
    }

    @HostListener('window:keydown.escape', ['$event'])
    onEsc(e: Event): void {
        if (e instanceof KeyboardEvent) {
            e.preventDefault();
            e.stopPropagation();
        }
        this.tryClose();
    }
}
