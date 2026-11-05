import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, ConfirmationDialogService } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import {
    catchError,
    concatMap,
    EMPTY,
    filter,
    finalize,
    from,
    map,
    Observable,
    of,
    repeat,
    Subscription,
    switchMap,
    timer,
    toArray,
} from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { BUILDING_WHEEL_STATUSES, CustomLibrary, Wheel, WHEEL_FILE_SUFFIXES } from '../../models/custom-library.model';
import { CustomLibrariesApiService } from '../../services/custom-libraries-api.service';
import { VenvStatusBadgeComponent } from '../venv-status-badge/venv-status-badge.component';

const POLL_INTERVAL_MS = 2_000;

export interface CustomLibraryDialogData {
    library?: CustomLibrary;
}

/** The created library, `'changed'` when versions of an existing one were added or removed, and
 *  `null` when the list the dialog was opened from has nothing to reload. */
export type CustomLibraryDialogResult = CustomLibrary | 'changed' | null;

@Component({
    selector: 'app-custom-library-dialog',
    imports: [
        MatTooltipModule,
        AppSvgIconComponent,
        ButtonComponent,
        TooltipOnOverflowDirective,
        VenvStatusBadgeComponent,
    ],
    templateUrl: './custom-library-dialog.component.html',
    styleUrls: ['./custom-library-dialog.component.scss'],
})
export class CustomLibraryDialogComponent {
    readonly data = inject<CustomLibraryDialogData | null>(DIALOG_DATA, { optional: true }) ?? {};

    /** Set as soon as the library exists, so a failed upload leaves the dialog managing what was
     *  created instead of offering to create it a second time. */
    readonly library = signal<CustomLibrary | null>(this.data.library ?? null);
    readonly isManaging = computed(() => this.library() !== null);

    readonly wheels = signal<Wheel[]>([]);
    readonly isLoadingWheels = signal(false);
    /** Files chosen before the library exists; uploaded one after another once it does. */
    readonly stagedFiles = signal<File[]>([]);
    readonly isSubmitting = signal(false);
    readonly isUploading = signal(false);
    readonly deletePending = signal(false);

    /** Unnamed while the library exists but a source archive still has to build: nothing has told
     *  it its distribution yet. */
    readonly title = computed(() => {
        const library = this.library();
        if (!library) return 'Create Custom Library';
        return library.name ?? 'Naming pending…';
    });
    readonly submitLabel = computed(() => (this.isSubmitting() ? 'Creating...' : 'Create'));
    readonly canUpload = computed(() => this.permissions.can(ResourceCode.CustomLibraries, ActionCode.Create));
    readonly canDeleteWheel = computed(() => this.permissions.can(ResourceCode.CustomLibraries, ActionCode.Delete));

    protected readonly fileAccept = WHEEL_FILE_SUFFIXES.join(',');

    // Whether anything was uploaded or removed, so the list behind the dialog knows to reload.
    private changed = false;
    private pollSubscription: Subscription | null = null;

    private readonly dialogRef = inject<DialogRef<CustomLibraryDialogResult>>(DialogRef);
    private readonly customLibrariesApi = inject(CustomLibrariesApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        if (this.library()) this.loadWheels(true);
    }

    /** Wheels and source archives chosen in the file picker: staged while the library is still to
     *  be created, uploaded straight away once it exists. Names the files it refuses rather than
     *  dropping them quietly. Either kind can create the library -- a wheel names it at once, a
     *  source archive leaves it unnamed until a background build names it. */
    onFilesSelected(event: Event): void {
        const input = event.target as HTMLInputElement;
        const chosen = Array.from(input.files ?? []);
        // The same file can be picked twice in a row, and the picker emits nothing on the second
        // pick unless its value is cleared.
        input.value = '';

        const accepted = chosen.filter((file) => this.hasWheelSuffix(file.name));
        for (const file of chosen) {
            if (!accepted.includes(file)) {
                this.toastService.error(`"${file.name}" is not a wheel or a source archive`);
            }
        }
        if (!accepted.length) return;

        const library = this.library();
        if (!library) {
            this.stagedFiles.update((files) => [...files, ...accepted]);
            return;
        }
        this.uploadAll(library, accepted);
    }

    removeStagedFile(index: number): void {
        this.stagedFiles.update((files) => files.filter((_, position) => position !== index));
    }

    submit(): void {
        const files = this.stagedFiles();
        if (!files.length || this.isSubmitting()) return;

        this.isSubmitting.set(true);
        const [first, ...rest] = files;
        // Counts the first file too: it is `files[0]`, already spent on creating the library, so a
        // later failure is reported against the right file in `files` by the same index.
        let uploaded = 1;
        this.customLibrariesApi
            .createCustomLibrary(first)
            .pipe(
                switchMap((library: CustomLibrary) => {
                    this.library.set(library);
                    if (!rest.length) return of(library);
                    return from(rest).pipe(
                        concatMap((file) => this.customLibrariesApi.uploadWheel(library.id, file)),
                        map(() => (uploaded += 1)),
                        toArray(),
                        map(() => library)
                    );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (library) => this.dialogRef.close(library),
                error: (error: HttpErrorResponse) => {
                    this.isSubmitting.set(false);
                    const library = this.library();
                    if (!library) {
                        this.toastService.error(extractHttpErrorMessage(error));
                        return;
                    }
                    // The library is there, a version is not: say which file stopped and leave the
                    // dialog on that library, so the rest are added rather than created again.
                    this.changed = true;
                    this.stagedFiles.set([]);
                    this.toastService.error(
                        `Library created, but "${files[uploaded].name}" was not uploaded: ${extractHttpErrorMessage(error)}`
                    );
                    this.loadWheels(true);
                },
            });
    }

    onDeleteWheel(wheel: Wheel): void {
        const library = this.library();
        if (!library || this.deletePending()) return;
        this.deletePending.set(true);
        // `confirmDelete` completes without emitting when it is dismissed, so `finalize` is what
        // clears the pending flag on both the delete and the dismissed-dialog paths.
        this.confirmationDialogService
            .confirmDelete(this.wheelLabel(wheel))
            .pipe(
                filter((confirmed) => confirmed === true),
                switchMap(() => this.customLibrariesApi.deleteWheel(library.id, wheel.id)),
                finalize(() => this.deletePending.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.changed = true;
                    this.loadWheels();
                },
                error: (error: HttpErrorResponse) => this.toastService.error(extractHttpErrorMessage(error)),
            });
    }

    /** What a version is called in the list and in its delete confirmation. */
    wheelLabel(wheel: Wheel): string {
        return wheel.version ?? wheel.wheel_filename ?? wheel.source_filename ?? `#${wheel.id}`;
    }

    cancel(): void {
        this.dialogRef.close(null);
    }

    close(): void {
        this.dialogRef.close(this.changed ? 'changed' : null);
    }

    private uploadAll(library: CustomLibrary, files: File[]): void {
        this.isUploading.set(true);
        let uploaded = 0;
        from(files)
            .pipe(
                concatMap((file) => this.customLibrariesApi.uploadWheel(library.id, file)),
                map(() => (uploaded += 1)),
                toArray(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.isUploading.set(false);
                    this.changed = true;
                    this.loadWheels();
                },
                error: (error: HttpErrorResponse) => {
                    this.isUploading.set(false);
                    if (uploaded > 0) this.changed = true;
                    this.toastService.error(
                        `"${files[uploaded].name}" was not uploaded: ${extractHttpErrorMessage(error)}`
                    );
                    this.loadWheels();
                },
            });
    }

    private loadWheels(showLoader = false): void {
        const library = this.library();
        if (!library) return;
        this.stopPolling();
        if (showLoader) this.isLoadingWheels.set(true);
        this.customLibrariesApi
            .getWheels(library.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (wheels) => {
                    this.isLoadingWheels.set(false);
                    this.applyWheels(wheels);
                },
                error: (error: HttpErrorResponse) => {
                    this.isLoadingWheels.set(false);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    private applyWheels(wheels: Wheel[]): void {
        this.wheels.set(wheels);
        if (wheels.some((wheel) => BUILDING_WHEEL_STATUSES.has(wheel.status))) {
            this.startPolling();
        } else {
            this.stopPolling();
        }
        this.refreshLibraryIfUnnamed();
    }

    /** While a source archive created this library, its name is unknown until a build picks it up
     *  and names it; the title (and the list behind the dialog, once reloaded) only shows that once
     *  this re-fetches the library itself, which plain wheel polling never does. */
    private refreshLibraryIfUnnamed(): void {
        const library = this.library();
        if (!library || library.name !== null) return;
        this.customLibrariesApi
            .getCustomLibrary(library.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((refreshed) => {
                if (refreshed.name !== null) this.changed = true;
                this.library.set(refreshed);
            });
    }

    private startPolling(): void {
        const library = this.library();
        if (!library || this.pollSubscription) return;
        // timer + repeat: the next request is scheduled only after the previous response arrived.
        this.pollSubscription = timer(POLL_INTERVAL_MS)
            .pipe(
                filter(() => document.visibilityState === 'visible'),
                switchMap(() => this.wheelsOrNothing(library.id)),
                repeat(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((wheels) => this.applyWheels(wheels));
    }

    private wheelsOrNothing(libraryId: number): Observable<Wheel[]> {
        return this.customLibrariesApi.getWheels(libraryId).pipe(catchError(() => EMPTY));
    }

    private stopPolling(): void {
        this.pollSubscription?.unsubscribe();
        this.pollSubscription = null;
    }

    private hasWheelSuffix(name: string): boolean {
        const lowered = name.toLowerCase();
        return WHEEL_FILE_SUFFIXES.some((suffix) => lowered.endsWith(suffix));
    }
}
