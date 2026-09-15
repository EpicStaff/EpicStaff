import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { AgentSurfacePlace } from '../../../../models/agent-definition.model';
import {
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    Surface,
    SurfaceSaveError,
} from '../../../../models/surface.model';
import { SurfaceCategoryId } from '../../../../models/surface-category.model';
import { SurfaceCardComponent } from '../agent-detail/agent-surfaces-panel/surface-card/surface-card.component';

@Component({
    selector: 'app-surface-detail',
    imports: [SurfaceCardComponent],
    templateUrl: './surface-detail.component.html',
    styleUrls: ['./surface-detail.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceDetailComponent {
    private readonly permissionService = inject(PermissionsService);

    surface = input<Surface | null>(null);
    isCreating = input<boolean>(false);
    readOnly = input<boolean>(false);
    isShared = input<boolean>(false);
    showMeta = input<boolean>(false);
    currentPlace = input<SurfaceCategoryId | null>(null);
    surfacePlaces = input<AgentSurfacePlace[]>([]);
    placesBusy = input<boolean>(false);
    saveError = input<SurfaceSaveError | null>(null);

    readonly canEditSurfaces = computed(() => this.permissionService.can(ResourceCode.Surfaces, ActionCode.Update));

    readonly create = output<CreateSurfaceRequest>();
    readonly rename = output<string>();
    readonly surfaceChange = output<PartialUpdateSurfaceRequest>();
    readonly openSource = output<void>();
    readonly detach = output<void>();
    readonly makeShared = output<void>();
    readonly makeAgentSpecificCopy = output<void>();
    readonly setSurfacePlaces = output<AgentSurfacePlace[]>();
    readonly duplicate = output<void>();
    readonly deleteSurface = output<void>();
}
