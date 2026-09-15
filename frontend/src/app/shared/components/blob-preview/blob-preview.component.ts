import { DecimalPipe, JsonPipe } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { renderAsync } from 'docx-preview';
import * as Papa from 'papaparse';
import type { Sheet as ExcelSheet } from 'read-excel-file/browser';
import readXlsxFile from 'read-excel-file/browser';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons/button/button.component';

type PreviewType = 'text' | 'json' | 'pdf' | 'image' | 'sheet' | 'docx' | 'unsupported';

interface SheetData {
    sheetNames: string[];
    activeSheet: string;
    headers: string[];
    rows: string[][];
}

@Component({
    selector: 'app-blob-preview',
    templateUrl: './blob-preview.component.html',
    styleUrls: ['./blob-preview.component.scss'],
    imports: [DecimalPipe, JsonPipe, AppSvgIconComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BlobPreviewComponent {
    blob = input<Blob | null>(null);
    fileName = input<string>('');
    size = input<number | null | undefined>(null);
    showDownload = input<boolean>(false);
    downloadClick = output<void>();

    private sanitizer = inject(DomSanitizer);

    previewType = signal<PreviewType>('unsupported');
    textContent = signal<string>('');
    jsonContent = signal<object | null>(null);
    pdfUrl = signal<SafeResourceUrl | null>(null);
    imageUrl = signal<string | null>(null);
    sheetData = signal<SheetData | null>(null);
    docxBlob = signal<Blob | null>(null);
    docxContainer = viewChild<ElementRef<HTMLDivElement>>('docxContainer');
    isLoading = signal<boolean>(false);
    previewError = signal<string | null>(null);
    csvDelimiter = signal<string>('auto');

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
    private processVersion = 0;

    constructor() {
        effect(() => {
            this.processBlob(this.blob(), this.fileName());
        });
        effect(() => {
            const blob = this.docxBlob();
            const container = this.docxContainer();
            if (blob && container) {
                this.renderDocx(blob, container.nativeElement);
            }
        });
    }

    get isCsv(): boolean {
        return this.getExtension(this.fileName()) === 'csv';
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

    private processBlob(blob: Blob | null, fileName: string): void {
        const version = ++this.processVersion;
        this.revokeBlobUrl();
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

        if (!blob || !fileName) {
            this.previewType.set('unsupported');
            this.isLoading.set(!blob && !!fileName);
            return;
        }

        const ext = this.getExtension(fileName);
        const type = this.resolvePreviewType(ext);
        this.previewType.set(type);

        if (type === 'unsupported') return;

        this.isLoading.set(true);
        this.handleBlob(blob, type, version);
    }

    private handleBlob(blob: Blob, type: PreviewType, version: number): void {
        const guard = () => version === this.processVersion;

        switch (type) {
            case 'text':
                blob.text().then((text) => {
                    if (!guard()) return;
                    this.textContent.set(text);
                    this.isLoading.set(false);
                });
                break;
            case 'json':
                blob.text().then((text) => {
                    if (!guard()) return;
                    try {
                        this.jsonContent.set(JSON.parse(text));
                    } catch {
                        this.textContent.set(text);
                        this.previewType.set('text');
                    }
                    this.isLoading.set(false);
                });
                break;
            case 'pdf': {
                const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
                this.currentBlobUrl = url;
                this.pdfUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(url));
                this.isLoading.set(false);
                break;
            }
            case 'image': {
                const url = URL.createObjectURL(blob);
                this.currentBlobUrl = url;
                this.imageUrl.set(url);
                this.isLoading.set(false);
                break;
            }
            case 'docx':
                this.docxBlob.set(blob);
                this.isLoading.set(false);
                break;
            case 'sheet':
                if (this.isCsv) {
                    blob.text().then((text) => {
                        if (!guard()) return;
                        this.currentCsvText = text;
                        this.sheetData.set(this.parseCsv(text, this.csvDelimiter()));
                        this.isLoading.set(false);
                    });
                } else {
                    blob.arrayBuffer().then(async (buf) => {
                        if (!guard()) return;
                        try {
                            const sheets = await readXlsxFile(buf);
                            if (!guard()) return;
                            this.currentSheets = sheets;
                            const sheetNames = sheets.map((s) => s.sheet);
                            const firstSheet = sheets[0];
                            this.sheetData.set(this.rowsToSheetData(sheetNames, firstSheet.sheet, firstSheet.data));
                        } catch {
                            this.previewError.set('Failed to parse spreadsheet');
                        }
                        this.isLoading.set(false);
                    });
                }
                break;
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
        if (textExts.includes(ext)) return 'text';
        if (ext === 'json') return 'json';
        if (ext === 'pdf') return 'pdf';
        if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'image';
        if (['xlsx', 'xlsm', 'csv'].includes(ext)) return 'sheet';
        if (ext === 'docx') return 'docx';
        return 'unsupported';
    }

    private getExtension(fileName: string): string {
        return fileName.split('.').pop()?.toLowerCase() ?? '';
    }

    private revokeBlobUrl(): void {
        if (this.currentBlobUrl) {
            URL.revokeObjectURL(this.currentBlobUrl);
            this.currentBlobUrl = null;
        }
    }
}
