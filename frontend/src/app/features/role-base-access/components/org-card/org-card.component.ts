import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, input } from '@angular/core';
import { GetOrganizationResponse } from '@shared/models';
import { AprilFoolsOrgNamePipe } from '../../../../shared/pipes/april-fools-org-name.pipe';

import { OrgAvatarComponent } from '../org-avatar/org-avatar.component';

@Component({
    selector: 'app-org-card',
    imports: [OrgAvatarComponent, AprilFoolsOrgNamePipe],
    templateUrl: './org-card.component.html',
    styleUrls: ['./org-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrgCardComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);

    organization = input.required<GetOrganizationResponse>();

    // onOpen(): void {
    //     const id = this.organization().id;
    //
    //     this.dialog.open(OrganizationDetailsDialogComponent, {
    //         width: 'calc(100vw - 2rem)',
    //         height: 'calc(100vh - 2rem)',
    //         disableClose: true,
    //         data: { id },
    //     });
    // }
}
