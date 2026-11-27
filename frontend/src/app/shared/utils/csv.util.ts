import { downloadBlob } from './download-blob.util';

export type CsvCell = string | number | null | undefined;

export function toCsv(rows: CsvCell[][]): string {
    return rows.map((row) => row.map(toCsvCell).join(',')).join('\r\n');
}

export function downloadCsv(rows: CsvCell[][], filename: string): void {
    downloadBlob(new Blob(['﻿' + toCsv(rows)], { type: 'text/csv;charset=utf-8' }), filename);
}

function toCsvCell(value: CsvCell): string {
    const text = typeof value === 'string' && /^[=+\-@\t\r]/.test(value) ? `'${value}` : String(value ?? '');
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
