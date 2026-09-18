import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterOutlet } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, RouteTab, RouteTabsComponent } from '@shared/components';
import { EMPTY } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { PasswordChangeDialogComponent } from '../../components/password-change-dialog/password-change-dialog.component';
import { ProfileEditDialogComponent } from '../../components/profile-edit-dialog/profile-edit-dialog.component';
import { UserAvatarComponent } from '../../components/user-avatar/user-avatar.component';

@Component({
    selector: 'app-profile-page',
    templateUrl: './profile-page.component.html',
    styleUrls: ['./profile-page.component.scss'],
    imports: [
        RouterOutlet,
        AppSvgIconComponent,
        ButtonComponent,
        UserAvatarComponent,
        RouteTabsComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilePageComponent implements OnInit {
    private dialog = inject(Dialog);
    private currentUserService = inject(ProfileService);
    private authService = inject(AuthService);
    private destroyRef = inject(DestroyRef);

    protected user = this.currentUserService.currentUserSignal;
    protected isLoading = signal(!this.currentUserService.currentUserSignal());

    protected readonly tabs: RouteTab[] = [
        { routerLink: 'overview', icon: 'home', label: 'Overview', isPermitted: () => true },
        { routerLink: 'api-keys', icon: 'key', label: 'API Keys', isPermitted: () => true },
    ];

    ngOnInit(): void {
        if (this.user()) {
            this.isLoading.set(false);
            return;
        }
        this.currentUserService
            .getCurrentUser()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.isLoading.set(false),
                error: () => this.isLoading.set(false),
            });
    }

    onPasswordChange(): void {
        this.dialog.open(PasswordChangeDialogComponent, {
            width: '560px',
        });
    }

    onSignOut(): void {
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

    onProfileEdit(): void {
        const user = this.user();
        if (!user) return;
        this.dialog.open(ProfileEditDialogComponent, {
            width: '560px',
            data: { name: user.display_name, email: user.email, avatarUrl: user.avatar_url },
        });
    }
}
