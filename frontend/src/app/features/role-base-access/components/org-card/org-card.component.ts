import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { GetOrganizationResponse } from '@shared/models';
import { EMPTY } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';

@Component({
    selector: 'app-org-card',
    imports: [OrgAvatarComponent],
    templateUrl: './org-card.component.html',
    styleUrls: ['./org-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '(click)': 'onOpen()',
    },
})
export class OrgCardComponent {
    private router = inject(Router);
    private profileService = inject(ProfileService);
    private toast = inject(ToastService);

    organization = input.required<GetOrganizationResponse>();

    onOpen(): void {
        const id = this.organization().id;

        this.profileService
            .switchOrg(id)
            .pipe(
                catchError((err) => {
                    this.toast.error(err.error.message);
                    return EMPTY;
                })
            )
            .subscribe(() => {
                this.router.navigateByUrl('/projects/my');
            });
    }
}
