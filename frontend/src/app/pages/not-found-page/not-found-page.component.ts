import { Location } from '@angular/common';
import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';

import { PermissionsService } from '../../services/auth/permissions.service';

@Component({
    selector: 'app-not-found-page',
    standalone: true,
    imports: [],
    templateUrl: './not-found-page.component.html',
    styleUrl: './not-found-page.component.scss',
})
export class NotFoundPageComponent {
    private readonly router = inject(Router);
    private readonly location = inject(Location);
    private readonly permissionsService = inject(PermissionsService);

    goBack(): void {
        this.location.back();
    }

    openWorkspace(): void {
        void this.router.navigate([this.permissionsService.resolveDefaultRoute()]);
    }
}
