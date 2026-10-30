import { AriaDescriber } from '@angular/cdk/a11y';
import { Injectable } from '@angular/core';

function collapseWhitespace(text: string | null | undefined): string {
    return (text ?? '').replace(/\s+/g, ' ').trim();
}

function isFormField(element: Element): element is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
    return (
        element instanceof HTMLInputElement ||
        element instanceof HTMLTextAreaElement ||
        element instanceof HTMLSelectElement
    );
}

/** The text a screen reader names the element by, taken from the first source it finds, in the order it looks. */
function accessibleName(element: Element): string {
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) {
        const labelText = collapseWhitespace(
            labelledBy
                .split(/\s+/)
                .map((id) => element.ownerDocument.getElementById(id)?.textContent ?? '')
                .join(' ')
        );
        if (labelText) return labelText;
    }

    const ariaLabel = collapseWhitespace(element.getAttribute('aria-label'));
    if (ariaLabel) return ariaLabel;

    if (isFormField(element)) {
        const labelText = collapseWhitespace(Array.from(element.labels ?? [], (label) => label.textContent).join(' '));
        if (labelText) return labelText;
        return element instanceof HTMLSelectElement ? '' : collapseWhitespace(element.placeholder);
    }

    return collapseWhitespace(element.textContent);
}

/**
 * Keeps a tooltip that only repeats its control's name out of the control's description. MatTooltip registers its
 * message as an `aria-describedby` description, and the CDK skips it only when it equals the `aria-label`, so a text
 * button read "Save, button, Save" and a labelled field read its label twice. A tooltip that differs from the name
 * stays the description. MatTooltip removes and describes again on every message change, so a new message is checked
 * again; a name that changes while the message stays is not. Removing a description that was never added is already a
 * no-op in the CDK.
 */
@Injectable()
export class TooltipAriaDescriber extends AriaDescriber {
    override describe(hostElement: Element, message: string, role?: string): void;
    override describe(hostElement: Element, message: HTMLElement): void;
    override describe(hostElement: Element, message: string | HTMLElement, role?: string): void {
        if (typeof message !== 'string') {
            super.describe(hostElement, message);
            return;
        }
        if (collapseWhitespace(message) === accessibleName(hostElement)) return;
        super.describe(hostElement, message, role);
    }
}
