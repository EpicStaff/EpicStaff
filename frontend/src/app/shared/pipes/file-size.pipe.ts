import { Pipe, PipeTransform } from '@angular/core';

export type FileSizeDecimalPlaces = number | 'auto';

@Pipe({
    name: 'fileSize',
})
export class FileSizePipe implements PipeTransform {
    /**
     * @param bytes
     * @param decimalPlaces Fixed decimal count, or `'auto'` for 0 dp up to KB and 1 dp for MB+.
     */
    transform(bytes: number | null | undefined, decimalPlaces: FileSizeDecimalPlaces = 0): string {
        if (bytes === null || isNaN(Number(bytes)) || !Number(bytes)) return '0 B';

        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const k = 1024;

        const b = Number(bytes);

        const i = Math.floor(Math.log(b) / Math.log(k));
        const unitIndex = Math.min(i, units.length - 1);
        const value = b / Math.pow(k, unitIndex);

        const dp = decimalPlaces === 'auto' ? (unitIndex >= 2 ? 1 : 0) : decimalPlaces;
        const formatted = dp > 0 ? value.toFixed(dp) : Math.round(value).toString();

        return `${formatted} ${units[unitIndex]}`;
    }
}
