import { ChangeDetectionStrategy, Component, inject, input, model } from '@angular/core';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { GetMeResponse } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { QuickStartTourService } from '../../../quick-start-tour/quick-start-tour.service';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-user-menu',
    imports: [AppSvgIconComponent, UserAvatarComponent],
    templateUrl: './user-menu.component.html',
    styleUrls: ['./user-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserMenuComponent {
    private authService = inject(AuthService);
    private router = inject(Router);
    private readonly quickStartTourService = inject(QuickStartTourService);

    user = input.required<GetMeResponse>();

    isUserMenuOpen = model<boolean>(false);

    protected readonly canStartQuickStartTour = this.quickStartTourService.isAvailable;

    onProfileClick(): void {
        this.isUserMenuOpen.set(false);
        void this.router.navigate(['/profile']);
    }

    onQuickStartTourClick(): void {
        this.isUserMenuOpen.set(false);
        void this.quickStartTourService.start();
    }

    onSignOutClick(): void {
        this.isUserMenuOpen.set(false);
        this.authService
            .logout()
            .pipe(
                catchError(() => {
                    this.authService.removeTokenAndNavToLogin();
                    return EMPTY;
                })
            )
            .subscribe();
    }
}
