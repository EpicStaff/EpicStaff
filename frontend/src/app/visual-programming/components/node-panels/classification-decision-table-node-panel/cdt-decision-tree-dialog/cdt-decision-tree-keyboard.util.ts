import { mainKeyFromEvent } from '../../../../core/keymap/key-chord.util';

/**
 * Keyboard policy for the Decision Tree dialog.
 *
 * A read-only viewer must not mutate the flow behind it, and the flow page's
 * global shortcuts do exactly that: the page's Ctrl+S runs a real
 * `POST /api/graphs/{id}/save/`, Escape saves the open panel and Delete deletes the
 * selected node. Not every one of them exempts text fields.
 *
 * The dialog feeds this from `DialogRef.keydownEvents`, which CDK dispatches from a
 * bubble-phase listener on `document.body` — earlier than the editor's `window`
 * keymap listener, which does not capture, so `stopPropagation()` here preempts it. The
 * subscriber must stay synchronous: deferring it past the dispatcher's stack frame
 * makes `stopPropagation` and `preventDefault` no-ops.
 *
 * Only the page's own shortcut set is swallowed; typing, Tab and Enter or Space
 * activating a block have already reached their target and pass through.
 *
 * Pure and Angular-free so the policy can be unit-tested without a dialog.
 */

export type CdtTreeKeyAction =
    | 'clear-search'
    | 'collapse-search'
    | 'close-detail'
    | 'close-explain-menu'
    | 'close-search'
    | 'close-dialog'
    | 'none';

export interface CdtTreeKeyState {
    /** Whether the docked detail window is showing a block. */
    readonly detailOpen: boolean;
    /** Whether the model picker over that window is showing. */
    readonly explainMenuOpen: boolean;
    /** Whether the dropdown under the search box is showing. */
    readonly searchOpen: boolean;
    /** Whether the search box itself is showing, beside its icon button. */
    readonly searchExpanded: boolean;
    readonly searchHasText: boolean;
    readonly targetIsSearch: boolean;
}

export interface CdtTreeKeyResult {
    readonly action: CdtTreeKeyAction;
    readonly stopPropagation: boolean;
    readonly preventDefault: boolean;
}

type CdtTreeKeyEvent = Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey'>;

/** Keys the page acts on with no modifier held. */
const PAGE_BARE_KEYS: ReadonlySet<string> = new Set(['Escape', 'Delete', 'Backspace']);

/** Keys the page acts on with Ctrl or Cmd held, named as the editor keymap names them. */
const PAGE_MODIFIER_KEYS: ReadonlySet<string> = new Set(['KeyC', 'KeyV', 'KeyZ', 'KeyY', 'KeyS', 'KeyF', 'Slash']);

function isSaveCombo(event: CdtTreeKeyEvent): boolean {
    return (event.ctrlKey || event.metaKey) && mainKeyFromEvent(event) === 'KeyS';
}

/**
 * Whether the page would act on this key.
 *
 * Deliberately a closed list rather than "everything except typing": swallowing
 * by default also swallowed Enter and Space, which left the blocks impossible to
 * activate from the keyboard.
 */
function isPageShortcut(event: CdtTreeKeyEvent): boolean {
    if (PAGE_BARE_KEYS.has(event.key)) {
        return true;
    }

    if (!(event.ctrlKey || event.metaKey)) {
        return false;
    }

    return PAGE_MODIFIER_KEYS.has(mainKeyFromEvent(event));
}

export function resolveTreeKeyAction(event: CdtTreeKeyEvent, state: CdtTreeKeyState): CdtTreeKeyResult {
    const escape = event.key === 'Escape';
    const save = isSaveCombo(event);
    const action = escape ? resolveEscapeAction(state) : 'none';

    return {
        action,
        // Shielding, not consuming: Delete, Backspace and Ctrl+Z are stopped so
        // the canvas behind never sees them, but are not prevented, so nothing
        // native is lost. Inside our own search box the page already exempts text
        // fields for most keys; of those it acts on regardless of target, only
        // Escape and Ctrl+S are swallowed there, so Ctrl+F still reaches the canvas search.
        stopPropagation: isPageShortcut(event) && (!state.targetIsSearch || escape || save),
        // Only for what we act on, so typing, native undo and copy still work.
        preventDefault: save || action !== 'none',
    };
}

/**
 * Innermost first: the model picker, then the search dropdown, then the text in
 * the focused box, then the box itself, then the docked window, then the dialog —
 * otherwise the whole dialog closes underneath whatever the user meant to dismiss.
 *
 * The search dropdown leads because it is the only real overlay left. The detail
 * window used to lead, back when it was an anchored popover that could not coexist
 * with the search panel; docked, it outranks only the dialog.
 */
function resolveEscapeAction(state: CdtTreeKeyState): CdtTreeKeyAction {
    // First: of everything Escape can mean, a menu is the innermost. It cannot be
    // open alongside the search dropdown, but only because the dialog stands one
    // down when the other opens — both hang off the toolbar, so nothing structural
    // separates them. See `openSearch` and `openExplainMenu`.
    if (state.explainMenuOpen) {
        return 'close-explain-menu';
    }

    if (state.searchOpen) {
        return 'close-search';
    }

    // Behind `close-search` because the caret stays in the box while the dropdown
    // is open — testing the text first would empty it on an Escape meant for the
    // dropdown. Ahead of `collapse-search` because emptying a box is smaller than
    // dismissing it.
    if (state.targetIsSearch && state.searchHasText) {
        return 'clear-search';
    }

    if (state.searchExpanded) {
        return 'collapse-search';
    }

    if (state.detailOpen) {
        return 'close-detail';
    }

    return 'close-dialog';
}
