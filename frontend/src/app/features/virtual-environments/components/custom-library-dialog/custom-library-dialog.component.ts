import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    DragDropAreaComponent,
    FileUploaderComponent,
    HelpTooltipComponent,
} from '@shared/components';
import { EnterSubmitDirective, TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import {
    catchError,
    concat,
    concatMap,
    EMPTY,
    filter,
    from,
    map,
    Observable,
    of,
    repeat,
    Subscription,
    switchMap,
    tap,
    timer,
    toArray,
} from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { BUILDING_WHEEL_STATUSES, CustomLibrary, Wheel, WHEEL_FILE_SUFFIXES } from '../../models/custom-library.model';
import { CustomLibrariesApiService } from '../../services/custom-libraries-api.service';
import {
    detectedLibraryName,
    diagnoseStagedWheels,
    hasIssue,
    STAGED_WHEEL_ISSUE_TEXT,
    StagedWheel,
} from '../../utils/staged-wheel';
import { VenvStatusBadgeComponent } from '../venv-status-badge/venv-status-badge.component';

const POLL_INTERVAL_MS = 2_000;

export interface CustomLibraryDialogData {
    library?: CustomLibrary;
}

/** The created library, `'changed'` when an existing one gained or lost versions, and `null` when
 *  the list the dialog was opened from has nothing to reload. */
export type CustomLibraryDialogResult = CustomLibrary | 'changed' | null;

/** One line of the Versions list: a version the library already holds, or a file about to become
 *  one. Both carry a label on the right -- a number, a build status, or what is wrong with it. */
export interface VersionRow {
    readonly key: string;
    readonly filename: string;
    readonly version: string | null;
    readonly wheel: Wheel | null;
    readonly staged: StagedWheel | null;
}

@Component({
    selector: 'app-custom-library-dialog',
    imports: [
        MatTooltipModule,
        AppSvgIconComponent,
        ButtonComponent,
        DragDropAreaComponent,
        FileUploaderComponent,
        HelpTooltipComponent,
        EnterSubmitDirective,
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
    /** Versions marked for deletion. Nothing is deleted until the dialog is saved. */
    readonly removedWheelIds = signal<ReadonlySet<number>>(new Set<number>());
    /** Files chosen in this dialog, in the order they were chosen. */
    readonly chosenFiles = signal<File[]>([]);
    readonly isSaving = signal(false);

    readonly keptWheels = computed(() => this.wheels().filter((wheel) => !this.removedWheelIds().has(wheel.id)));

    /** Every chosen file with what its name says and what is wrong with it, read against the
     *  versions the library keeps and the files chosen before it. */
    readonly staged = computed<StagedWheel[]>(() =>
        diagnoseStagedWheels(this.chosenFiles(), {
            libraryName: this.library()?.name ?? null,
            storedVersions: this.keptWheels()
                .map((wheel) => wheel.version)
                .filter((version): version is string => version !== null),
        })
    );

    readonly rows = computed<VersionRow[]>(() => [
        ...this.keptWheels().map((wheel) => ({
            key: `wheel-${wheel.id}`,
            filename: wheel.wheel_filename ?? wheel.source_filename ?? '',
            version: wheel.version,
            wheel,
            staged: null,
        })),
        ...this.staged().map((staged, index) => ({
            key: `file-${index}-${staged.file.name}`,
            filename: staged.file.name,
            version: staged.issue === null ? staged.version : null,
            wheel: null,
            staged,
        })),
    ]);

    /** The name the library has, or the one its first readable file gives it. */
    readonly detectedName = computed(() => this.library()?.name ?? detectedLibraryName(this.staged()));
    readonly uploadableFiles = computed(() =>
        this.staged()
            .filter((staged) => !hasIssue(staged))
            .map((staged) => staged.file)
    );

    readonly title = computed(() => {
        const library = this.library();
        if (!library) return 'Create Custom Library';
        return library.name ?? 'Naming pending...';
    });
    readonly submitLabel = computed(() => (this.isManaging() ? 'Save Changes' : 'Create Library'));
    readonly canSubmit = computed(
        () => this.uploadableFiles().length > 0 || (this.isManaging() && this.removedWheelIds().size > 0)
    );
    readonly canUpload = computed(() => this.permissions.can(ResourceCode.CustomLibraries, ActionCode.Create));
    readonly canDeleteWheel = computed(() => this.permissions.can(ResourceCode.CustomLibraries, ActionCode.Delete));

    protected readonly fileHint = 'Wheel (.whl) or source archive (.tar.gz, .zip) · Max 100 MB per file';
    protected readonly nameHint =
        'Read off the first file you add and spelled the way a package index would. A venv installs the library under this name, which is why it cannot be typed or changed.';
    // Named without their dot: the drop overlay spells them out in capitals.
    protected readonly allowedTypes = WHEEL_FILE_SUFFIXES.map((suffix) => suffix.slice(1));
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    // Whether anything reached the backend, so the list behind the dialog knows to reload.
    private changed = false;
    private pollSubscription: Subscription | null = null;

    private readonly dialogRef = inject<DialogRef<CustomLibraryDialogResult>>(DialogRef);
    private readonly customLibrariesApi = inject(CustomLibrariesApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        if (this.library()) this.loadWheels(true);
    }

    /** Files chosen in the picker or dropped on the area. Nothing is refused here: a file this
     *  dialog cannot use gets a line of its own saying why, which is the point of the list. */
    onFilesChosen(files: FileList): void {
        const chosen = Array.from(files);
        if (!chosen.length) return;
        this.chosenFiles.update((current) => [...current, ...chosen]);
    }

    onFilePicked(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) this.onFilesChosen(input.files);
        // The same file can be picked twice in a row, and the picker stays quiet on the second
        // pick unless its value is cleared.
        input.value = '';
    }

    /** Take a line out: a chosen file is forgotten, a stored version is marked for deletion and
     *  goes when the dialog is saved. */
    removeRow(row: VersionRow): void {
        if (this.isSaving()) return;
        if (row.wheel) {
            const id = row.wheel.id;
            this.removedWheelIds.update((ids) => new Set([...ids, id]));
            return;
        }
        const file = row.staged?.file;
        this.chosenFiles.update((files) => files.filter((candidate) => candidate !== file));
    }

    /** What the line shows on its right: a build status, a version, or what is wrong with it. */
    issueText(row: VersionRow): { label: string; reason: string } | null {
        const issue = row.staged?.issue;
        return issue ? STAGED_WHEEL_ISSUE_TEXT[issue] : null;
    }

    submit(): void {
        if (!this.canSubmit() || this.isSaving()) return;
        this.isSaving.set(true);
        const files = this.uploadableFiles();
        const library = this.library();

        if (!library) {
            this.create(files);
            return;
        }
        this.applyChanges(library, files);
    }

    cancel(): void {
        this.dialogRef.close(this.changed ? 'changed' : null);
    }

    private create(files: File[]): void {
        const [first, ...rest] = files;
        this.customLibrariesApi
            .createCustomLibrary(first)
            .pipe(
                switchMap((library) => {
                    this.library.set(library);
                    this.changed = true;
                    this.forget([first]);
                    // `toArray`, so the chain answers once however many files it uploaded.
                    return this.uploadEach(library, rest).pipe(
                        toArray(),
                        map(() => library)
                    );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (library) => this.settle(library),
                error: (error: HttpErrorResponse) => this.reportFailure(error),
            });
    }

    private applyChanges(library: CustomLibrary, files: File[]): void {
        const removals = [...this.removedWheelIds()].map((id) => this.customLibrariesApi.deleteWheel(library.id, id));

        concat(...removals, this.uploadEach(library, files))
            .pipe(toArray(), takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.changed = true;
                    this.removedWheelIds.set(new Set<number>());
                    this.settle(library);
                },
                error: (error: HttpErrorResponse) => {
                    this.changed = true;
                    this.reportFailure(error);
                },
            });
    }

    /** Upload the files one after another, forgetting each as it lands: what is left in the list
     *  after a failure is exactly what still has to go. */
    private uploadEach(library: CustomLibrary, files: File[]): Observable<unknown> {
        if (!files.length) return of(null);
        return from(files).pipe(
            concatMap((file) =>
                this.customLibrariesApi.uploadWheel(library.id, file).pipe(tap(() => this.forget([file])))
            )
        );
    }

    private forget(files: File[]): void {
        this.chosenFiles.update((current) => current.filter((file) => !files.includes(file)));
    }

    /** Close when everything the dialog was asked to do is done; stay open on the files it could
     *  not use, so the refusal is read where it was made. */
    private settle(library: CustomLibrary): void {
        this.isSaving.set(false);
        if (this.chosenFiles().length === 0) {
            this.dialogRef.close(this.data.library ? 'changed' : library);
            return;
        }
        this.toastService.success(
            this.data.library ? 'Versions saved' : `Custom library "${library.name ?? ''}" created`
        );
        this.loadWheels();
    }

    private reportFailure(error: HttpErrorResponse): void {
        this.isSaving.set(false);
        this.toastService.error(extractHttpErrorMessage(error));
        if (this.library()) this.loadWheels();
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
}
