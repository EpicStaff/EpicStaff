import { OverlayKeyboardDispatcher, OverlayRef } from '@angular/cdk/overlay';
import { Injectable } from '@angular/core';
import { TOOLTIP_PANEL_CLASS } from '@angular/material/tooltip';
import { Subject } from 'rxjs';

function isTooltip(overlayRef: OverlayRef): boolean {
    return overlayRef.overlayElement.classList.contains(TOOLTIP_PANEL_CLASS);
}

/**
 * Hands a key to the dialog or menu the user is working in before a tooltip. A tooltip shows whenever its control has
 * keyboard focus and sits on top of every overlay, so Material let it take the first Escape and a dialog or menu needed
 * a second press. A tooltip still takes Escape when no other overlay wants it, so it stays dismissible on its own.
 *
 * Every other key already passes a tooltip by (its predicate accepts Escape only) and reaches the overlay below it:
 * Enter reaches a dialog's `keydownEvents`, which `EnterSubmitDirective` submits on, while a tooltip shows.
 *
 * Relies on the CDK's internal `_attachedOverlays` and `OverlayRef._keydownEvents` (the stream `canReceiveEvent` is
 * asked about): check this class when upgrading `@angular/cdk`.
 */
@Injectable()
export class TooltipLastKeyboardDispatcher extends OverlayKeyboardDispatcher {
    protected override canReceiveEvent<T>(overlayRef: OverlayRef, event: Event, stream: Subject<T>): boolean {
        if (!super.canReceiveEvent(overlayRef, event, stream)) return false;
        if (!isTooltip(overlayRef)) return true;
        return !this._attachedOverlays.some(
            (other) => !isTooltip(other) && super.canReceiveEvent(other, event, other._keydownEvents)
        );
    }
}
