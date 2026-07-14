import { ChangeDetectionStrategy, Component, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import { AuthService } from '../../../../services/auth/auth.service';

@Component({
    selector: 'app-unassigned-user-page',
    templateUrl: './unassigned-user-page.component.html',
    styleUrls: ['./unassigned-user-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, FormsModule, ReactiveFormsModule, ButtonComponent],
})
export class UnassignedUserPageComponent {
    private authService = inject(AuthService);
    private destroyRef = inject(DestroyRef);

    onSignOut(): void {
        this.authService.logout().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }
}
