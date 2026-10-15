import { Directive, effect, inject, TemplateRef, ViewContainerRef } from '@angular/core';

import { FlowReadOnlyService } from '../../services/flow-readonly.service';

/**
 * Renders the element only while this editor may change the flow: not for a user without
 * Flows:Update, and not in a version preview. Use it for editing controls inside the editor
 * instead of a plain Flows:Update permission check, which misses the preview.
 */
@Directive({
    selector: '[appIfFlowEditable]',
})
export class IfFlowEditableDirective {
    private readonly templateRef = inject(TemplateRef<unknown>);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly flowReadOnly = inject(FlowReadOnlyService);

    constructor() {
        effect(() => {
            this.viewContainerRef.clear();
            if (!this.flowReadOnly.isReadOnly()) {
                this.viewContainerRef.createEmbeddedView(this.templateRef);
            }
        });
    }
}
