import { Directive, effect, inject, input, TemplateRef, ViewContainerRef } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';

@Directive({
    selector: '[appHasPermission]',
})
export class HasPermissionDirective {
    private readonly tpl = inject(TemplateRef<unknown>);
    private readonly vcr = inject(ViewContainerRef);
    private readonly perms = inject(PermissionsService);

    public appHasPermission = input.required<[ResourceCode | undefined, ActionCode | ActionCode[]]>();

    constructor() {
        effect(() => {
            const v = this.appHasPermission();
            this.vcr.clear();

            const [resource, action] = v;

            if (!resource) {
                this.vcr.createEmbeddedView(this.tpl);
                return;
            }

            const allowed = Array.isArray(action)
                ? this.perms.canAny(resource, action)
                : this.perms.can(resource, action);

            if (allowed) {
                this.vcr.createEmbeddedView(this.tpl);
            }
        });
    }
}
