import { Pipe, PipeTransform } from '@angular/core';

import { formatExecutionDataForDisplay } from '../utils/json-parser.util';

@Pipe({
    name: 'formatExecutionData',
    standalone: true,
})
export class FormatExecutionDataPipe implements PipeTransform {
    transform(value: Record<string, unknown>): Record<string, unknown> {
        return formatExecutionDataForDisplay(value);
    }
}
