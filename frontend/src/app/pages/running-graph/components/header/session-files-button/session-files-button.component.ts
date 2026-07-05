import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    inject,
    input,
    OnDestroy,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';

import {
    ExportSessionFilesDialogComponent,
    ExportSessionFilesDialogData,
} from '../../../../../features/files/components/export-session-files-dialog/export-session-files-dialog.component';
import { SessionOutputFile } from '../../../../../features/files/models/storage.models';
import { StorageApiService } from '../../../../../features/files/services/storage-api.service';
import { GraphSessionStatus } from '../../../../../features/flows/services/flows-sessions.service';
import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CollapseOnOverflowDirective } from '../../../../../shared/directives/collapse-on-overflow.directive';

const TERMINAL_STATUSES = new Set([
    GraphSessionStatus.ENDED,
    GraphSessionStatus.ERROR,
    GraphSessionStatus.STOP,
    GraphSessionStatus.EXPIRED,
]);

// Backend may finish indexing output files slightly after the session status
// becomes terminal. Poll with backoff until files appear or we give up.
const POST_TERMINAL_RETRY_DELAYS_MS = [1000, 2000, 4000];

@Component({
    selector: 'app-session-files-button',
    standalone: true,
    imports: [AppSvgIconComponent, CollapseOnOverflowDirective, MatTooltip],
    templateUrl: './session-files-button.component.html',
    styleUrls: ['./session-files-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SessionFilesButtonComponent implements OnInit, OnDestroy {
    readonly sessionId = input.required<string>();
    readonly sessionStatus = input<GraphSessionStatus | null>(null);

    private retryTimeoutId: ReturnType<typeof setTimeout> | null = null;

    private readonly storageApiService = inject(StorageApiService);
    private readonly dialog = inject(Dialog);
    private readonly destroyRef = inject(DestroyRef);

    readonly isLoaded = signal(false);
    readonly outputFiles = signal<SessionOutputFile[]>([]);

    constructor() {
        effect(() => {
            const status = this.sessionStatus();
            if (status && TERMINAL_STATUSES.has(status)) {
                this.loadFiles(0);
            }
        });
    }

    ngOnInit(): void {
        this.loadFiles(0);
    }

    ngOnDestroy(): void {
        this.cancelPendingRetry();
    }

    openDialog(): void {
        if (this.outputFiles().length === 0) return;
        this.dialog.open<unknown, ExportSessionFilesDialogData>(ExportSessionFilesDialogComponent, {
            data: {
                sessionId: this.sessionId(),
                outputFiles: this.outputFiles(),
            },
            panelClass: 'custom-dialog-panel',
        });
    }

    private cancelPendingRetry(): void {
        if (this.retryTimeoutId !== null) {
            clearTimeout(this.retryTimeoutId);
            this.retryTimeoutId = null;
        }
    }

    private loadFiles(attempt: number): void {
        this.cancelPendingRetry();
        this.storageApiService
            .getSessionOutputFiles(this.sessionId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (files) => {
                    this.outputFiles.set(files);
                    this.isLoaded.set(true);
                    this.maybeScheduleRetry(files.length, attempt);
                },
                error: () => {
                    this.outputFiles.set([]);
                    this.isLoaded.set(true);
                },
            });
    }

    private maybeScheduleRetry(fileCount: number, attempt: number): void {
        if (fileCount > 0) return;
        const status = this.sessionStatus();
        if (!status || !TERMINAL_STATUSES.has(status)) return;
        if (attempt >= POST_TERMINAL_RETRY_DELAYS_MS.length) return;

        const delay = POST_TERMINAL_RETRY_DELAYS_MS[attempt];
        this.retryTimeoutId = setTimeout(() => {
            this.retryTimeoutId = null;
            this.loadFiles(attempt + 1);
        }, delay);
    }
}
