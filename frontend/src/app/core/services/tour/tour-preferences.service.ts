import { inject, Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';

@Injectable({
    providedIn: 'root',
})
export class TourPreferencesService {
    private readonly profileService = inject(ProfileService);

    public hasCompletedQuickStartTour$(): Observable<boolean> {
        void this.profileService;
        return of(false);
    }

    public markQuickStartTourCompleted(): Observable<void> {
        return of(void 0);
    }
}
