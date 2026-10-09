import { inject, Injectable, Signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, map, of } from 'rxjs';

import { RecycleBinSettingsApiService } from './recycle-bin-settings-api.service';

/** Recycle-bin settings. Global, so they are fetched once, the first time anything injects this service. */
@Injectable({ providedIn: 'root' })
export class RecycleBinSettingsStorageService {
    private readonly api = inject(RecycleBinSettingsApiService);

    /** Days an item stays in the bin. `null` until loaded, or when the request failed. */
    readonly retentionDays: Signal<number | null> = toSignal(
        this.api.getSettings().pipe(
            map((response) => response.retention_days),
            catchError(() => of(null))
        ),
        { initialValue: null }
    );
}
