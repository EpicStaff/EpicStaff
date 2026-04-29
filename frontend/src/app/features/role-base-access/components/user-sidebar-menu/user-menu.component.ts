import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { GetMeResponse, Membership } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-user-menu',
    imports: [CommonModule, AppSvgIconComponent, UserAvatarComponent, OrgAvatarComponent],
    templateUrl: './user-menu.component.html',
    styleUrls: ['./user-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserMenuComponent {
    private authService = inject(AuthService);

    public user = input.required<GetMeResponse>();
    public organizations = computed<Membership[]>(() => this.user().memberships);

    isUserMenuOpen = model<boolean>(false);

    public onSignOutClick(): void {
        this.isUserMenuOpen.set(false);
        this.authService
            .logout()
            .pipe(
                catchError(() => {
                    this.authService.removeTokensAndNavToLogin();
                    return EMPTY;
                })
            )
            .subscribe();
    }
}
