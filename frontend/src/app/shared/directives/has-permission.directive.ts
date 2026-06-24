import { Directive, effect, inject, Input, signal, TemplateRef, ViewContainerRef } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';

@Directive({
    selector: '[appHasPermission]',
})
export class HasPermissionDirective {
    private readonly tpl = inject(TemplateRef<unknown>);
    private readonly vcr = inject(ViewContainerRef);
    private readonly perms = inject(PermissionsService);

    private readonly value = signal<[ResourceCode, ActionCode] | null>(null);

    constructor() {
        effect(() => {
            const v = this.value();
            this.vcr.clear();
            if (v !== null && this.perms.can(v[0], v[1])) {
                this.vcr.createEmbeddedView(this.tpl);
            }
        });
    }

    @Input() set appHasPermission(value: [ResourceCode, ActionCode]) {
        this.value.set(value);
    }
}
