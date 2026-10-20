import { BreakpointObserver } from '@angular/cdk/layout';
import { inject, Injectable } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';

import { BREAKPOINTS } from '../constants/breakpoints';

/** Whether the screen is a phone's (`BREAKPOINTS.phone`), where the pages that support phones show one column at a time. */
@Injectable({ providedIn: 'root' })
export class PhoneLayoutService {
    readonly isPhone = toSignal(
        inject(BreakpointObserver)
            .observe(BREAKPOINTS.phone)
            .pipe(map(({ matches }) => matches)),
        { initialValue: false }
    );
}
