import { inject, LOCALE_ID, Pipe, PipeTransform } from '@angular/core';
import { formatInZone } from '@shared/utils';

import { UserPreferencesService } from '../../services/auth/user-preferences.service';

type DateValue = Date | string | number;

/**
 * Angular's `date` pipe in the user's display timezone: the same format strings, the same `null` for no value.
 * Impure, so a date on screen follows a change of the display timezone; it formats again only when the value, the
 * format or the zone changed. Date pickers keep the built-in pipe: they show calendar days of the browser.
 */
@Pipe({
    name: 'userDate',
    pure: false,
})
export class UserDatePipe implements PipeTransform {
    private readonly displayZone = inject(UserPreferencesService).displayZone;
    private readonly locale = inject(LOCALE_ID);

    private lastValue: DateValue | null = null;
    private lastTime = NaN;
    private lastFormat = '';
    private lastZone = '';
    private lastResult: string | null = null;

    transform(value: DateValue | null | undefined, format = 'mediumDate'): string | null {
        if (value === null || value === undefined || value === '' || Number.isNaN(value)) return null;
        const zone = this.displayZone();
        // A Date can be changed in place, so its time is compared, not just the object.
        const time = value instanceof Date ? value.getTime() : NaN;
        const unchanged =
            value === this.lastValue &&
            (!(value instanceof Date) || Object.is(time, this.lastTime)) &&
            format === this.lastFormat &&
            zone === this.lastZone;
        if (!unchanged) {
            this.lastResult = formatInZone(value, format, this.locale, zone);
            this.lastValue = value;
            this.lastTime = time;
            this.lastFormat = format;
            this.lastZone = zone;
        }
        return this.lastResult;
    }
}
