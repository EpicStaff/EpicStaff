/**
 * Keyboard policy for the Decision Tree dialog.
 *
 * A read-only viewer must not be able to mutate the flow behind it, and the flow
 * page is covered in global shortcuts that do exactly that:
 *
 * - `FlowVisualProgrammingComponent.handleCtrlS` — a `document:keydown`
 *   `@HostListener` that calls `onHeaderSave()`, i.e. a real
 *   `POST /api/graphs/{id}/save/`
 * - `ShortcutListenerDirective` — a `window` keydown subscription, live twice
 *   (node panel shell + main canvas), where Escape saves the open panel and
 *   Delete removes the selected node
 *
 * The listener therefore has to run in the **capture** phase on `window`.
 * A bubble-phase listener on `document` is not enough: `handleCtrlS` sits on the
 * same node and was registered first, and `stopPropagation` does not stop other
 * listeners on the same node — only `stopImmediatePropagation` does, which would
 * not help for listeners registered earlier. Capture on `window` is the only
 * point that precedes all of them.
 *
 * Typing still has to work in the dialog's own search box, so events targeted at
 * it pass through — except the two the page would act on regardless of target.
 *
 * Pure and Angular-free so the policy can be unit-tested without a dialog.
 */

export type CdtTreeKeyAction = 'clear-search' | 'close-popover' | 'close-dialog' | 'none';

export interface CdtTreeKeyState {
    readonly popoverOpen: boolean;
    readonly searchHasText: boolean;
    readonly targetIsSearch: boolean;
}

export interface CdtTreeKeyResult {
    readonly action: CdtTreeKeyAction;
    readonly stopPropagation: boolean;
    readonly preventDefault: boolean;
}

type CdtTreeKeyEvent = Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey'>;

function isSaveCombo(event: CdtTreeKeyEvent): boolean {
    return (event.ctrlKey || event.metaKey) && event.code === 'KeyS';
}

export function resolveTreeKeyAction(event: CdtTreeKeyEvent, state: CdtTreeKeyState): CdtTreeKeyResult {
    const escape = event.key === 'Escape';
    const save = isSaveCombo(event);
    const action = escape ? resolveEscapeAction(state) : 'none';

    // Everything is swallowed, except ordinary typing in our own search box.
    // Save and Escape are swallowed even there: the page's Ctrl+S handler does
    // not exempt text fields, and Escape is ours to interpret.
    const stopPropagation = !state.targetIsSearch || escape || save;

    return {
        action,
        stopPropagation,
        // Only for what we act on, so typing, selection and native copy still work.
        preventDefault: save || action !== 'none',
    };
}

function resolveEscapeAction(state: CdtTreeKeyState): CdtTreeKeyAction {
    // Innermost first: the popover is a separate overlay without a focus trap,
    // so without this precedence the whole dialog would close underneath it.
    if (state.popoverOpen) {
        return 'close-popover';
    }

    if (state.targetIsSearch && state.searchHasText) {
        return 'clear-search';
    }

    return 'close-dialog';
}
