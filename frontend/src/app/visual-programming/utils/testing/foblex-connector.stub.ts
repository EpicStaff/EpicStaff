import { Directive, input } from '@angular/core';

/**
 * Stands in for Foblex's `fNodeInput` / `fNodeOutput` in a node component rendered without a canvas (the
 * real ones need the canvas around them). It shows which connectors a template draws, under the same
 * `data-f-output-id` / `data-f-input-id` attributes the real directives set.
 */
@Directive({
    // Foblex's own selectors, so a node template binds to this stub unchanged.
    // eslint-disable-next-line @angular-eslint/directive-selector
    selector: '[fNodeOutput], [fNodeInput]',
    host: {
        '[attr.data-f-output-id]': 'fOutputId()',
        '[attr.data-f-input-id]': 'fInputId()',
    },
})
export class FoblexConnectorStubDirective {
    readonly fOutputId = input<string>();
    readonly fInputId = input<string>();
    readonly fOutputMultiple = input<boolean>();
    readonly fInputMultiple = input<boolean>();
    readonly fOutputDisabled = input<boolean>();
    readonly fInputDisabled = input<boolean>();
    readonly fOutputConnectableSide = input<string>();
    readonly fInputConnectableSide = input<string>();
    readonly fCanBeConnectedInputs = input<string[]>();
    readonly isSelfConnectable = input<boolean>();
}
