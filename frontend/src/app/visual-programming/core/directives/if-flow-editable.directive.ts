import { Directive, effect, inject, input, TemplateRef, ViewContainerRef } from '@angular/core';

import { FlowReadOnlyService } from '../../services/flow-readonly.service';

/**
 * Renders the element only while this editor may change the flow: not for a user without
 * Flows:Update, and not in a version preview. Use it for editing controls inside the editor
 * instead of a plain Flows:Update permission check, which misses the preview. A panel can also pass its own
 * condition (`*appIfFlowEditable="!isReadOnly()"`), e.g. one that includes a lock on the node.
 */
@Directive({
    selector: '[appIfFlowEditable]',
})
export class IfFlowEditableDirective {
    private readonly templateRef = inject(TemplateRef<unknown>);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly flowReadOnly = inject(FlowReadOnlyService);

    /** Extra condition; the bare attribute leaves it empty and only the editor's read-only state decides. */
    readonly appIfFlowEditable = input<boolean | ''>('');

    constructor() {
        effect(() => {
            this.viewContainerRef.clear();
            if (!this.flowReadOnly.isReadOnly() && this.appIfFlowEditable() !== false) {
                this.viewContainerRef.createEmbeddedView(this.templateRef);
            }
        });
    }
}
