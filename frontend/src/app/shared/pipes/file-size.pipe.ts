import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
    name: 'fileSize',
})
export class FileSizePipe implements PipeTransform {
    transform(bytes: number | null | undefined, decimalPlaces = 0): string {
        if (bytes === null || isNaN(Number(bytes)) || !Number(bytes)) return '0 B';

        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const k = 1024;

        let b = Number(bytes);

        const i = Math.floor(Math.log(b) / Math.log(k));
        const unitIndex = Math.min(i, units.length - 1);
        const value = b / Math.pow(k, unitIndex);

        const formatted = decimalPlaces > 0 ? value.toFixed(decimalPlaces) : Math.round(value).toString();

        return `${formatted} ${units[unitIndex]}`;
    }
}
