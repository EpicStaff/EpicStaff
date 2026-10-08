import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
    name: 'auditJson',
})
export class AuditJsonPipe implements PipeTransform {
    public transform(value: unknown): string {
        if (value === null || value === undefined || isEmptyObject(value)) {
            return '';
        }
        return JSON.stringify(value, null, 2);
    }
}

function isEmptyObject(value: unknown): boolean {
    return typeof value === 'object' && value !== null && !Array.isArray(value) && Object.keys(value).length === 0;
}
