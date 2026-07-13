import { DecimalPipe, JsonPipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { renderAsync } from 'docx-preview';
import * as Papa from 'papaparse';
import type { Sheet as ExcelSheet } from 'read-excel-file/browser';
import readXlsxFile from 'read-excel-file/browser';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageApiService } from '../../../../../../services/storage-api.service';
import { getFileExtension } from '../../../../../../utils/storage-file.utils';

type PreviewType = 'text' | 'json' | 'pdf' | 'image' | 'sheet' | 'docx' | 'unsupported';

export interface SheetData {
    sheetNames: string[];
    activeSheet: string;
    headers: string[];
    rows: string[][];
}

@Component({
    selector: 'app-storage-preview',
    imports: [DecimalPipe, JsonPipe, AppSvgIconComponent, ButtonComponent, MatTooltipModule],
    templateUrl: './storage-preview.component.html',
    styleUrls: ['./storage-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoragePreviewComponent {
    item = input<StorageItem | null>(null);
    selectedItems = input<StorageItem[]>([]);
    showSidebar = input(true);
    toggleSidebar = output<void>();
    contextAction = output<{ action: string; item: StorageItem; selectedItems?: StorageItem[] }>();
    breadcrumbClick = output<string>();

    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private sanitizer = inject(DomSanitizer);

    previewType = signal<PreviewType>('unsupported');
    textContent = signal<string>('');
    jsonContent = signal<object | null>(null);
    pdfUrl = signal<SafeResourceUrl | null>(null);
    imageUrl = signal<string | null>(null);
    sheetData = signal<SheetData | null>(null);
    docxBlob = signal<Blob | null>(null);
    docxContainer = viewChild<ElementRef<HTMLDivElement>>('docxContainer');
    isLoadingPreview = signal<boolean>(false);
    previewError = signal<string | null>(null);
    csvDelimiter = signal<string>('auto');

    kebabMenuOpen = signal<boolean>(false);
    kebabMenuPosition = signal<{ right: number; top: number }>({ right: 0, top: 0 });

    readonly csvDelimiters = [
        { label: 'Auto', value: 'auto' },
        { label: 'Comma (,)', value: ',' },
        { label: 'Semicolon (;)', value: ';' },
        { label: 'Tab (\\t)', value: '\t' },
        { label: 'Pipe (|)', value: '|' },
    ];

    private currentBlobUrl: string | null = null;
    private currentCsvText: string | null = null;
    private currentSheets: ExcelSheet[] | null = null;

    constructor() {
        effect(() => {
            this.loadPreview(this.item());
        });
        effect(() => {
            const blob = this.docxBlob();
            const container = this.docxContainer();
            if (blob && container) {
                this.renderDocx(blob, container.nativeElement);
            }
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

    get fileExtension(): string {
        const item = this.item();
        if (!item) return '';
        return getFileExtension(item.name);
    }

    get previewBadge(): string | null {
        switch (this.previewType()) {
            case 'text':
                return 'TXT';
            case 'json':
                return 'JSON';
            default:
                return null;
        }
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

    onKebabMenuAction(action: string): void {
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

    get isCsv(): boolean {
        return getFileExtension(this.item()?.name ?? '') === 'csv';
    }

    onSheetChange(sheetName: string): void {
        if (!this.currentSheets) return;
        const sheet = this.currentSheets.find((s) => s.sheet === sheetName);
        if (!sheet) return;
        const sheetNames = this.currentSheets.map((s) => s.sheet);
        this.sheetData.set(this.rowsToSheetData(sheetNames, sheetName, sheet.data));
    }

    onDelimiterChange(delimiter: string): void {
        this.csvDelimiter.set(delimiter);
        if (this.currentCsvText !== null) {
            this.sheetData.set(this.parseCsv(this.currentCsvText, delimiter));
        }
    }

    private loadPreview(currentItem: StorageItem | null): void {
        this.revokeCurrentBlob();
        this.textContent.set('');
        this.jsonContent.set(null);
        this.pdfUrl.set(null);
        this.imageUrl.set(null);
        this.sheetData.set(null);
        this.docxBlob.set(null);
        this.currentSheets = null;
        this.currentCsvText = null;
        this.csvDelimiter.set('auto');
        this.previewError.set(null);

        if (!currentItem || currentItem.type === 'folder') {
            this.previewType.set('unsupported');
            return;
        }

        const ext = getFileExtension(currentItem.name);
        const type = this.resolvePreviewType(ext);
        this.previewType.set(type);

        if (type === 'unsupported') return;

        this.isLoadingPreview.set(true);
        this.storageApiService
            .downloadBlob(currentItem.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => this.handleBlob(blob, type),
                error: () => {
                    this.previewError.set('Failed to load file preview');
                    this.isLoadingPreview.set(false);
                },
            });
    }

    private handleBlob(blob: Blob, type: PreviewType): void {
        switch (type) {
            case 'text':
                blob.text().then((text) => {
                    this.textContent.set(text);
                    this.isLoadingPreview.set(false);
                });
                break;
            case 'json':
                blob.text().then((text) => {
                    try {
                        this.jsonContent.set(JSON.parse(text));
                    } catch {
                        this.textContent.set(text);
                        this.previewType.set('text');
                    }
                    this.isLoadingPreview.set(false);
                });
                break;
            case 'pdf': {
                const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
                this.currentBlobUrl = url;
                this.pdfUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(url));
                this.isLoadingPreview.set(false);
                break;
            }
            case 'image': {
                const url = URL.createObjectURL(blob);
                this.currentBlobUrl = url;
                this.imageUrl.set(url);
                this.isLoadingPreview.set(false);
                break;
            }
            case 'docx': {
                this.docxBlob.set(blob);
                this.isLoadingPreview.set(false);
                break;
            }
            case 'sheet': {
                if (this.isCsv) {
                    blob.text().then((text) => {
                        this.currentCsvText = text;
                        this.sheetData.set(this.parseCsv(text, this.csvDelimiter()));
                        this.isLoadingPreview.set(false);
                    });
                } else {
                    blob.arrayBuffer().then(async (buf) => {
                        try {
                            const sheets = await readXlsxFile(buf);
                            this.currentSheets = sheets;
                            const sheetNames = sheets.map((s) => s.sheet);
                            const firstSheet = sheets[0];
                            this.sheetData.set(this.rowsToSheetData(sheetNames, firstSheet.sheet, firstSheet.data));
                        } catch {
                            this.previewError.set('Failed to parse spreadsheet');
                        }
                        this.isLoadingPreview.set(false);
                    });
                }
                break;
            }
        }
    }

    private parseCsv(text: string, delimiter: string): SheetData {
        const config: Papa.ParseConfig = {
            header: false,
            skipEmptyLines: true,
        };
        if (delimiter !== 'auto') {
            config.delimiter = delimiter;
        }
        const result = Papa.parse<string[]>(text, config);
        const rows = result.data as string[][];
        const headers = rows.length > 0 ? rows[0].map(String) : [];
        const dataRows = rows.slice(1).map((r) => headers.map((_, i) => String(r[i] ?? '')));
        return { sheetNames: ['Sheet1'], activeSheet: 'Sheet1', headers, rows: dataRows };
    }

    private rowsToSheetData(
        sheetNames: string[],
        activeSheet: string,
        data: (string | number | boolean | typeof Date | null)[][]
    ): SheetData {
        const rows = data.map((row) => row.map((cell) => String(cell ?? '')));
        const headers = rows.length > 0 ? rows[0] : [];
        const dataRows = rows.slice(1).map((r) => headers.map((_, i) => r[i] ?? ''));
        return { sheetNames, activeSheet, headers, rows: dataRows };
    }

    private async renderDocx(blob: Blob, container: HTMLElement): Promise<void> {
        container.innerHTML = '';
        // .docx is a ZIP archive — verify the "PK\x03\x04" magic before rendering
        // so we can surface a clean error for misnamed/corrupt files.
        const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
        const isZip = head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04;
        if (!isZip) {
            this.previewError.set('File is not a valid .docx document');
            return;
        }
        try {
            // renderAltChunks=false: altChunk embeds raw HTML from the .docx
            // into an iframe srcdoc in the same origin — a known XSS vector.
            await renderAsync(blob, container, undefined, { renderAltChunks: false });
        } catch {
            this.previewError.set('Failed to render document preview');
        }
    }

    private resolvePreviewType(ext: string): PreviewType {
        const textExts = ['txt', 'md', 'log', 'py', 'js', 'ts', 'html', 'css', 'xml', 'yaml', 'yml'];
        const jsonExts = ['json'];
        const pdfExts = ['pdf'];
        const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'];
        const sheetExts = ['xlsx', 'xlsm', 'csv'];
        const docxExts = ['docx'];

        if (textExts.includes(ext)) return 'text';
        if (jsonExts.includes(ext)) return 'json';
        if (pdfExts.includes(ext)) return 'pdf';
        if (imageExts.includes(ext)) return 'image';
        if (sheetExts.includes(ext)) return 'sheet';
        if (docxExts.includes(ext)) return 'docx';
        return 'unsupported';
    }

    private revokeCurrentBlob(): void {
        if (this.currentBlobUrl) {
            URL.revokeObjectURL(this.currentBlobUrl);
            this.currentBlobUrl = null;
        }
    }
}
