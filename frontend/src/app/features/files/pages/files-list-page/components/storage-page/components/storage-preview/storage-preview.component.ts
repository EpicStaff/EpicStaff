import { CdkTrapFocus } from '@angular/cdk/a11y';
import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, BlobPreviewComponent, ButtonComponent, canPreviewFilePart } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';
import { catchError, EMPTY, Observable, switchMap, tap } from 'rxjs';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageApiService } from '../../../../../../services/storage-api.service';

// Above this size text-like files are previewed partially and other types not at all.
const MAX_PREVIEW_FILE_SIZE = 5 * 1024 * 1024;
// Bytes fetched for a partial preview; enough for what blob-preview renders.
const PARTIAL_PREVIEW_BYTES = 1024 * 1024;

type PreviewMode = 'none' | 'full' | 'partial' | 'too-large';

function resolvePreviewMode(item: StorageItem | null): PreviewMode {
    if (!item || item.type === 'folder') return 'none';
    if ((item.size ?? 0) <= MAX_PREVIEW_FILE_SIZE) return 'full';
    return canPreviewFilePart(item.name) ? 'partial' : 'too-large';
}

@Component({
    selector: 'app-storage-preview',
    imports: [
        CdkTrapFocus,
        AppSvgIconComponent,
        BlobPreviewComponent,
        ButtonComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    templateUrl: './storage-preview.component.html',
    styleUrls: ['./storage-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoragePreviewComponent {
    item = input<StorageItem | null>(null);
    selectedItems = input<StorageItem[]>([]);
    showSidebar = input(true);
    content = input<string | null>(null);
    readOnly = input<boolean>(false);
    toggleSidebar = output<void>();
    contextAction = output<{ action: string; item: StorageItem; selectedItems?: StorageItem[] }>();
    breadcrumbClick = output<string>();

    private readonly kebabButton = viewChild<ElementRef<HTMLButtonElement>>('kebabButton');
    private readonly toggleSidebarButton = viewChild.required<ElementRef<HTMLButtonElement>>('toggleSidebarButton');

    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private permissionsService = inject(PermissionsService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private lastFocusedHeaderControl: HTMLElement | null = null;

    previewBlob = signal<Blob | null>(null);
    isLoadingPreview = signal<boolean>(false);
    previewError = signal<string | null>(null);
    kebabMenuOpen = signal<boolean>(false);
    kebabMenuPosition = signal<{ right: number; top: number }>({ right: 0, top: 0 });
    readonly previewMode = computed(() => resolvePreviewMode(this.item()));

    constructor() {
        // switchMap drops the previous download, so a late answer can't land under the new file.
        toObservable(this.item)
            .pipe(
                switchMap((item) => this.loadPreview(item)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();

        // Deleting the shown item takes its header buttons away: hand the focus to the sidebar toggle, not `<body>`.
        effect(() => {
            this.item();
            untracked(() => afterNextRender(() => this.restoreLostHeaderFocus(), { injector: this.injector }));
        });
    }

    get breadcrumbs(): string[] {
        const item = this.item();
        if (!item) return [];
        return item.path.split('/').filter(Boolean);
    }

    get hasFileSelected(): boolean {
        const item = this.item();
        return !!item && item.type === 'file';
    }

    get canDownload(): boolean {
        return this.permissionsService.can(ResourceCode.Files, ActionCode.Export);
    }

    onDownload(): void {
        const item = this.item();
        if (item) {
            this.contextAction.emit({ action: 'download', item });
        }
    }

    onKebabClick(event: MouseEvent): void {
        event.stopPropagation();
        const btn = event.currentTarget as HTMLElement;
        const rect = btn.getBoundingClientRect();
        this.kebabMenuPosition.set({ right: window.innerWidth - rect.right, top: rect.bottom + 4 });
        this.kebabMenuOpen.set(true);
    }

    closeKebabMenu(): void {
        this.kebabMenuOpen.set(false);
    }

    /** Escape closes the menu, not a dialog around the page; its focus trap returns the focus to the ⋮ button. */
    closeKebabMenuOnEscape(event: Event): void {
        event.stopPropagation();
        this.closeKebabMenu();
    }

    /** Remembers the focused header control, so the focus can be recovered when it goes away with the item. */
    onHeaderFocusIn(event: FocusEvent): void {
        this.lastFocusedHeaderControl = event.target as HTMLElement;
    }

    onKebabMenuAction(action: string): void {
        if (this.kebabMenuOpen()) {
            // Off the menu item first: a dialog the action opens returns the focus to what had it, and the item goes away.
            this.kebabButton()?.nativeElement.focus();
        }
        this.kebabMenuOpen.set(false);
        const item = this.item();
        if (!item) return;
        const selectedItems = this.selectedItems();
        if (action === 'download' && selectedItems.length > 1) {
            this.contextAction.emit({ action: 'download-selected', item, selectedItems });
        } else {
            this.contextAction.emit({ action, item });
        }
    }

    private restoreLostHeaderFocus(): void {
        const lastFocused = this.lastFocusedHeaderControl;
        if (!lastFocused || lastFocused.isConnected) return;
        this.lastFocusedHeaderControl = null;
        if (!isFocusLost(this.document)) return;
        this.toggleSidebarButton().nativeElement.focus();
    }

    private loadPreview(currentItem: StorageItem | null): Observable<Blob> {
        const mode = resolvePreviewMode(currentItem);
        this.previewBlob.set(null);
        this.previewError.set(mode === 'too-large' ? 'File is too large to preview' : null);
        this.isLoadingPreview.set(mode === 'full' || mode === 'partial');

        if (!currentItem || !this.isLoadingPreview()) return EMPTY;

        return this.storageApiService
            .previewBlob(currentItem.path, mode === 'partial' ? PARTIAL_PREVIEW_BYTES : undefined)
            .pipe(
                tap((blob) => {
                    this.previewBlob.set(blob);
                    this.isLoadingPreview.set(false);
                }),
                catchError(() => {
                    this.previewError.set('Failed to load file preview');
                    this.isLoadingPreview.set(false);
                    return EMPTY;
                })
            );
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
