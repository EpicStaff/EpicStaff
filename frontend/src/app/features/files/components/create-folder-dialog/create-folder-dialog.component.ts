import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, HostListener, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { Spinner2Component } from '../../../../shared/components/spinner-type2/spinner.component';
import { StorageApiService } from '../../services/storage-api.service';

export interface CreateFolderDialogData {
    /** Pre-fill the destination folder path */
    folderPath?: string;
}

export interface AddFilesPayload {
    /** Full destination path: destinationPath + optional subfolder name */
    targetPath: string;
    files: File[];
    /** True when no files selected — only mkdir should be called */
    mkdirOnly: boolean;
}

export interface CreateFolderDialogResult {
    type: 'mkdir' | 'upload';
    path?: string;
    count?: number;
}

export interface FolderNode {
    name: string;
    path: string;
    level: number;
    isExpanded: boolean;
    isLoading: boolean;
    hasChildren: boolean;
    children: FolderNode[];
    isLoaded: boolean;
}

@Component({
    selector: 'app-create-folder-dialog',
    imports: [FormsModule, AppSvgIconComponent, Spinner2Component, MatIconModule, MatTooltipModule],
    templateUrl: './create-folder-dialog.component.html',
    styleUrls: ['./create-folder-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateFolderDialogComponent {
    private dialogRef = inject(DialogRef<CreateFolderDialogResult | undefined>);
    private data: CreateFolderDialogData = inject(DIALOG_DATA, { optional: true }) ?? {};
    private storageApiService = inject(StorageApiService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    private static readonly ARCHIVE_EXTENSIONS = new Set([
        'zip',
        'tar',
        'gz',
        'tgz',
        'bz2',
        'xz',
        'tar.gz',
        'tar.bz2',
        'tar.xz',
    ]);
    private static readonly BLOCKED_EXTENSIONS = new Set([
        'exe',
        'msi',
        'com',
        'scr',
        'pif',
        'bat',
        'cmd',
        'vbs',
        'vbe',
        'wsh',
        'wsf',
        'ps1',
        'psm1',
        'psd1',
        'sh',
        'bash',
        'csh',
        'ksh',
        'zsh',
        'app',
        'command',
        'elf',
        'jar',
        'war',
        'ear',
        'dll',
        'so',
        'dylib',
        'rar',
        '7z',
    ]);

    readonly folderName = signal('');
    readonly isDragging = signal(false);
    readonly files = signal<File[]>([]);

    // Destination folder dropdown
    readonly dropdownOpen = signal(false);
    readonly searchQuery = signal('');
    readonly rootNodes = signal<FolderNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly selectedPath = signal<string>('');

    private readonly allNodes = signal<FolderNode[]>([]);

    readonly visibleNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const roots = this.rootNodes();
        if (query) {
            const filtered = this.allNodes().filter((n) => n.name.toLowerCase().includes(query));
            const minLevel = filtered.reduce((min, n) => Math.min(min, n.level), Infinity);
            return filtered.map((n) => ({ ...n, level: n.level - minLevel }));
        }
        return this.buildVisible(roots);
    });

    get selectedFolderLabel(): string {
        const path = this.selectedPath();
        return path ? `/${path}` : '/';
    }

    readonly isUploading = signal(false);
    /** Maps filename → error label returned by the server (e.g. archive contains executables) */
    readonly fileServerErrors = signal<Map<string, string>>(new Map());
    readonly hasBlockedFiles = computed(
        () => this.files().some((f) => this.isBlocked(f) || this.isZeroSize(f)) || this.fileServerErrors().size > 0
    );
    readonly isValid = computed(
        () => !this.hasBlockedFiles() && (this.files().length > 0 || this.folderName().trim().length > 0)
    );
    readonly totalSize = computed(() => this.formatSize(this.files().reduce((sum, f) => sum + f.size, 0)));

    ngOnInit(): void {
        if (this.data.folderPath) {
            this.selectedPath.set(this.data.folderPath);
        }
        this.loadLevel('', null);
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        this.dropdownOpen.set(false);
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        this.dropdownOpen.update((v) => !v);
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
    }

    selectFolder(path: string): void {
        this.selectedPath.set(path);
        this.dropdownOpen.set(false);
    }

    isSelected(path: string): boolean {
        return this.selectedPath() === path;
    }

    toggleExpand(event: Event, node: FolderNode): void {
        event.stopPropagation();
        if (node.isExpanded) {
            node.isExpanded = false;
        } else {
            node.isExpanded = true;
            if (!node.isLoaded && node.hasChildren) {
                node.isLoading = true;
                this.loadLevel(node.path, node);
            }
        }
        this.rootNodes.update((n) => [...n]);
    }

    onDragOver(event: DragEvent): void {
        event.preventDefault();
        this.isDragging.set(true);
    }

    onDragLeave(event: DragEvent): void {
        event.preventDefault();
        const target = event.currentTarget as HTMLElement;
        const rect = target.getBoundingClientRect();
        if (
            event.clientX <= rect.left ||
            event.clientX >= rect.right ||
            event.clientY <= rect.top ||
            event.clientY >= rect.bottom
        ) {
            this.isDragging.set(false);
        }
    }

    onDrop(event: DragEvent): void {
        event.preventDefault();
        this.isDragging.set(false);
        const dropped = event.dataTransfer?.files;
        if (dropped?.length) {
            this.addFiles(Array.from(dropped));
        }
    }

    onFileInputChange(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files?.length) {
            this.addFiles(Array.from(input.files));
            input.value = '';
        }
    }

    removeFile(index: number): void {
        const removed = this.files()[index];
        this.files.update((list) => list.filter((_, i) => i !== index));
        if (removed && this.fileServerErrors().has(removed.name)) {
            this.fileServerErrors.update((m) => {
                const next = new Map(m);
                next.delete(removed.name);
                return next;
            });
        }
    }

    isArchive(file: File): boolean {
        const name = file.name.toLowerCase();
        if (name.match(/\.tar\.(gz|bz2|xz)$/)) return true;
        return CreateFolderDialogComponent.ARCHIVE_EXTENSIONS.has(name.split('.').pop() ?? '');
    }

    isBlocked(file: File): boolean {
        const ext = file.name.toLowerCase().split('.').pop() ?? '';
        return CreateFolderDialogComponent.BLOCKED_EXTENSIONS.has(ext);
    }

    isZeroSize(file: File): boolean {
        return file.size === 0;
    }

    getFileError(file: File): string | null {
        return this.fileServerErrors().get(file.name) ?? null;
    }

    formatSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    onConfirm(): void {
        if (!this.isValid() || this.isUploading()) return;
        const destination = this.selectedPath();
        const subfolder = this.folderName().trim();
        const targetPath = subfolder ? (destination ? `${destination}/${subfolder}` : subfolder) : destination;
        const files = this.files();

        this.isUploading.set(true);
        this.fileServerErrors.set(new Map());
        this.storageApiService
            .handleAddFilesResult({ targetPath, files, mkdirOnly: files.length === 0 })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (res) => this.dialogRef.close(res),
                error: (error: unknown) => {
                    this.isUploading.set(false);
                    const perFileErrors = this.extractPerFileErrors(error);
                    if (perFileErrors.size > 0) {
                        this.fileServerErrors.set(perFileErrors);
                    } else {
                        this.toastService.error(this.getUploadErrorMessage(error));
                    }
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    private loadLevel(path: string, parent: FolderNode | null): void {
        this.storageApiService
            .list(path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const folders = items
                        .filter((i) => i.type === 'folder')
                        .map(
                            (i): FolderNode => ({
                                name: i.name,
                                path: i.path || (path ? `${path}/${i.name}` : i.name),
                                level: parent ? parent.level + 1 : 0,
                                isExpanded: false,
                                isLoading: false,
                                hasChildren: !i.is_empty,
                                children: [],
                                isLoaded: false,
                            })
                        );

                    if (parent) {
                        parent.children = folders;
                        parent.isLoaded = true;
                        parent.isLoading = false;
                        parent.hasChildren = folders.length > 0;
                        if (folders.length === 0) parent.isExpanded = false;
                    } else {
                        this.rootNodes.set(folders);
                        this.isLoadingRoot.set(false);
                    }

                    this.rebuildAllNodes();
                    this.rootNodes.update((n) => [...n]);
                },
                error: () => {
                    if (parent) {
                        parent.isLoading = false;
                        parent.isLoaded = true;
                    } else {
                        this.isLoadingRoot.set(false);
                    }
                    this.rootNodes.update((n) => [...n]);
                },
            });
    }

    private buildVisible(nodes: FolderNode[]): FolderNode[] {
        const result: FolderNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.isExpanded && node.children.length > 0) {
                result.push(...this.buildVisible(node.children));
            }
        }
        return result;
    }

    private rebuildAllNodes(): void {
        this.allNodes.set(this.buildVisible(this.rootNodes()));
    }

    private addFiles(newFiles: File[]): void {
        this.files.update((existing) => {
            const names = new Set(existing.map((f) => f.name));
            return [...existing, ...newFiles.filter((f) => !names.has(f.name))];
        });
    }

    private extractPerFileErrors(error: unknown): Map<string, string> {
        const result = new Map<string, string>();
        if (!(error instanceof HttpErrorResponse) || error.status !== 400) return result;

        const message = this.getFullRawErrorText(error);
        if (!message) return result;

        // Matches both "contains executable files" and "contains protected files"
        const re = /Archive '([^']+)' contains (?:executable|protected) files/g;
        let match: RegExpExecArray | null;
        while ((match = re.exec(message)) !== null) {
            result.set(match[1], 'Contains restricted files');
        }

        return result;
    }

    /** Returns the widest possible string from the error body for regex scanning. */
    private getFullRawErrorText(error: HttpErrorResponse): string {
        const r = error.error;
        if (typeof r === 'string') return r;
        if (r && typeof r === 'object') {
            // Serialize the whole object so nested Python-dict strings are also scanned
            try {
                return JSON.stringify(r);
            } catch {
                const p = r as { detail?: unknown; message?: unknown; error?: unknown; reason?: unknown };
                const v = p.detail ?? p.message ?? p.error ?? p.reason;
                if (typeof v === 'string') return v;
            }
        }
        return '';
    }

    private getRawErrorMessage(error: HttpErrorResponse): string {
        const r = error.error;
        if (typeof r === 'string') return r;
        if (r && typeof r === 'object') {
            const p = r as { detail?: unknown; message?: unknown; error?: unknown; reason?: unknown };
            const v = p.detail ?? p.message ?? p.error ?? p.reason;
            if (typeof v === 'string') return v;
        }
        return '';
    }

    private getUploadErrorMessage(error: unknown): string {
        const fallbackMessage = 'Failed to upload files';
        if (!(error instanceof HttpErrorResponse)) return fallbackMessage;

        const responseError = error.error;
        if (typeof responseError === 'string' && responseError.trim()) return responseError;

        if (responseError && typeof responseError === 'object') {
            const payload = responseError as { detail?: unknown; error?: unknown; message?: unknown; reason?: unknown };
            const backendMessage = payload.detail ?? payload.error ?? payload.message ?? payload.reason;
            if (typeof backendMessage === 'string' && backendMessage.trim()) return backendMessage;
        }

        if (typeof error.message === 'string' && error.message.trim()) return error.message;
        return fallbackMessage;
    }
}
