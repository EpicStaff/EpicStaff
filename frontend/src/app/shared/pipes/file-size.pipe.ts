import { Pipe, PipeTransform } from '@angular/core';
import { FileSizeDecimalPlaces, formatFileSize } from '@shared/utils';

@Pipe({
    name: 'fileSize',
})
export class FileSizePipe implements PipeTransform {
    /**
     * @param bytes
     * @param decimalPlaces Fixed decimal count, or `'auto'` for 0 dp up to KB and 1 dp for MB+.
     */
    transform(bytes: number | null | undefined, decimalPlaces: FileSizeDecimalPlaces = 0): string {
        return formatFileSize(bytes, decimalPlaces);
    }
}
