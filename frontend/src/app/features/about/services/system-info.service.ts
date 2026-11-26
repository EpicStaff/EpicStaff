import { inject, Injectable, signal } from '@angular/core';
import { catchError, of } from 'rxjs';

import { FrontendBuild, SystemInfo } from '../models/system-info.model';
import { SystemInfoApiService } from './system-info-api.service';

const NO_FRONTEND_BUILD: FrontendBuild = { gitSha: null, commitDate: null };

/**
 * The running build, loaded once and kept for the whole page life: the backend's build and feature switches, and the
 * commit the frontend bundle was built from. Not a `*-storage` service registered with `APP_STORAGE`: nothing here
 * belongs to the signed-in user, so a logout has nothing to clear.
 */
@Injectable({ providedIn: 'root' })
export class SystemInfoService {
    private readonly systemInfoState = signal<SystemInfo | null>(null);
    private readonly frontendBuildState = signal<FrontendBuild>(NO_FRONTEND_BUILD);

    /** `null` until the request lands, and for good when it fails. */
    readonly systemInfo = this.systemInfoState.asReadonly();
    readonly frontendBuild = this.frontendBuildState.asReadonly();

    private readonly api = inject(SystemInfoApiService);
    private requested = false;

    /** Asks once; later calls do nothing. */
    load(): void {
        if (this.requested) {
            return;
        }
        this.requested = true;

        this.api
            .getSystemInfo()
            .pipe(catchError(() => of(null)))
            .subscribe((info) => this.systemInfoState.set(info));

        this.api
            .getFrontendBuild()
            .pipe(catchError(() => of(NO_FRONTEND_BUILD)))
            .subscribe((build) => this.frontendBuildState.set(build));
    }
}
