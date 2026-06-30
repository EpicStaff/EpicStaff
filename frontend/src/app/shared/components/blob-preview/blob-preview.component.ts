import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { DomSanitizer, SafeHtml, SafeResourceUrl } from '@angular/platform-browser';
import * as mammoth from 'mammoth';
import * as XLSX from 'xlsx';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

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
    imports: [JsonPipe, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BlobPreviewComponent {
    blob = input<Blob | null>(null);
    fileName = input<string>('');

    private sanitizer = inject(DomSanitizer);

    previewType = signal<PreviewType>('unsupported');
    textContent = signal<string>('');
    jsonContent = signal<object | null>(null);
    pdfUrl = signal<SafeResourceUrl | null>(null);
    imageUrl = signal<string | null>(null);
    sheetData = signal<SheetData | null>(null);
    docxHtml = signal<SafeHtml | null>(null);
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
    private currentWorkbook: XLSX.WorkBook | null = null;
    private processVersion = 0;

    constructor() {
        effect(() => {
            this.processBlob(this.blob(), this.fileName());
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
        if (!this.currentWorkbook) return;
        this.sheetData.set(this.parseSheet(this.currentWorkbook, sheetName));
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
        this.docxHtml.set(null);
        this.currentWorkbook = null;
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
                blob.arrayBuffer().then((buf) => {
                    if (!guard()) return;
                    mammoth.convertToHtml({ arrayBuffer: buf }).then((result) => {
                        if (!guard()) return;
                        this.docxHtml.set(this.sanitizer.bypassSecurityTrustHtml(result.value));
                        this.isLoading.set(false);
                    });
                });
                break;
            case 'sheet':
                if (this.isCsv) {
                    blob.text().then((text) => {
                        if (!guard()) return;
                        try {
                            this.currentCsvText = text;
                            this.sheetData.set(this.parseCsv(text, this.csvDelimiter()));
                        } catch {
                            this.previewError.set('Failed to parse CSV file');
                        }
                        this.isLoading.set(false);
                    });
                } else {
                    blob.arrayBuffer().then((buf) => {
                        if (!guard()) return;
                        try {
                            const wb = XLSX.read(buf, { type: 'array' });
                            this.currentWorkbook = wb;
                            this.sheetData.set(this.parseSheet(wb, wb.SheetNames[0]));
                        } catch {
                            this.previewError.set('Failed to parse spreadsheet file');
                        }
                        this.isLoading.set(false);
                    });
                }
                break;
        }
    }

    private parseCsv(text: string, delimiter: string): SheetData {
        const opts: XLSX.ParsingOptions = delimiter === 'auto' ? {} : { FS: delimiter };
        const wb = XLSX.read(text, { type: 'string', ...opts });
        return this.parseSheet(wb, wb.SheetNames[0]);
    }

    private parseSheet(wb: XLSX.WorkBook, sheetName: string): SheetData {
        const ws = wb.Sheets[sheetName];
        const rows: string[][] = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' }) as string[][];
        const headers = rows.length > 0 ? rows[0].map(String) : [];
        const dataRows = rows.slice(1).map((r) => headers.map((_, i) => String(r[i] ?? '')));
        return { sheetNames: wb.SheetNames, activeSheet: sheetName, headers, rows: dataRows };
    }

    private resolvePreviewType(ext: string): PreviewType {
        const textExts = ['txt', 'md', 'log', 'py', 'js', 'ts', 'html', 'css', 'xml', 'yaml', 'yml'];
        if (textExts.includes(ext)) return 'text';
        if (ext === 'json') return 'json';
        if (ext === 'pdf') return 'pdf';
        if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'image';
        if (['xlsx', 'xls', 'xlsm', 'ods', 'csv'].includes(ext)) return 'sheet';
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
