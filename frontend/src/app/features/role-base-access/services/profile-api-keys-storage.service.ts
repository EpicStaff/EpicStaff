import { inject, Injectable, signal } from '@angular/core';
import { GetMyApiKeyResponse } from '@shared/models';
import { Observable, tap } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';

/**
 * The signed-in user's API keys, shared by the profile page and its API keys tab so an action in the
 * page header (a password change revokes every key) is reflected in the tab. Provided by the profile
 * page, so the list lives only while the page is open and never outlives the user who loaded it.
 */
@Injectable()
export class ProfileApiKeysStorageService {
    private readonly keysSignal = signal<GetMyApiKeyResponse[]>([]);
    readonly keys = this.keysSignal.asReadonly();

    private readonly profileService = inject(ProfileService);

    refresh(): Observable<GetMyApiKeyResponse[]> {
        return this.profileService.getMyApiKeys().pipe(tap((keys) => this.keysSignal.set(keys)));
    }
}
