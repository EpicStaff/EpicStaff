/**
 * Keyboard policy for the Decision Tree dialog.
 *
 * A read-only viewer must not be able to mutate the flow behind it, and the flow
 * page is covered in global shortcuts that do exactly that:
 *
 * - `FlowVisualProgrammingComponent.handleCtrlS` — a `document:keydown`
 *   `@HostListener` that calls `onHeaderSave()`, i.e. a real
 *   `POST /api/graphs/{id}/save/`. It does not exempt text fields.
 * - `ShortcutListenerDirective` — a `window` keydown subscription, live three
 *   times (main canvas, node panel shell, shortcuts button), where Escape saves
 *   the open panel and Delete removes the selected node. It exempts text fields
 *   for everything except Escape.
 *
 * The dialog feeds this from `DialogRef.keydownEvents`, which CDK dispatches from
 * a bubble-phase listener on `document.body`. The event reaches `body` before
 * `document` or `window`, so a `stopPropagation()` there preempts every handler
 * above — none of them listens in the capture phase. The subscriber has to
 * stay synchronous: a `debounceTime` or a `setTimeout` would defer it past the
 * dispatcher's stack frame, and by then `stopPropagation` and `preventDefault`
 * are both no-ops.
 *
 * Only the page's own shortcut set is swallowed. Everything else — typing, Tab,
 * and Enter or Space activating a block — has already reached its target by the
 * time this runs, and is passed through untouched.
 *
 * Pure and Angular-free so the policy can be unit-tested without a dialog.
 */

export type CdtTreeKeyAction = 'clear-search' | 'close-detail' | 'close-search' | 'close-dialog' | 'none';

export interface CdtTreeKeyState {
    /** Whether the docked detail window is showing a block. */
    readonly detailOpen: boolean;
    readonly searchOpen: boolean;
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

/**
 * Keys the page acts on with Ctrl or Cmd held. The Cyrillic entries are the same
 * physical keys on a RU layout and are listed in the directive as well.
 */
const PAGE_MODIFIER_KEYS: ReadonlySet<string> = new Set(['c', 'с', 'v', 'м', 'z', 'я', 'y', 'н', 's', 'ы']);

function isSaveCombo(event: CdtTreeKeyEvent): boolean {
    return (event.ctrlKey || event.metaKey) && event.code === 'KeyS';
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

    // `KeyF` is `NodesSearchComponent`'s `document:keydown` handler, which opens
    // the canvas node search and guards nothing at all.
    return (
        event.code === 'KeyS' ||
        event.code === 'Slash' ||
        event.code === 'KeyF' ||
        PAGE_MODIFIER_KEYS.has(event.key.toLowerCase())
    );
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
        // fields, so only the two it acts on regardless of target are swallowed.
        stopPropagation: isPageShortcut(event) && (!state.targetIsSearch || escape || save),
        // Only for what we act on, so typing, native undo and copy still work.
        preventDefault: save || action !== 'none',
    };
}

/**
 * Topmost first, then the focused control, then the docked window, then the
 * dialog — otherwise the whole dialog closes underneath whatever the user meant to
 * dismiss.
 *
 * The search dropdown leads because it is the only real overlay left. The detail
 * window used to lead, back when it was an anchored popover that could not coexist
 * with the search panel; docked, it outranks only the dialog.
 */
function resolveEscapeAction(state: CdtTreeKeyState): CdtTreeKeyAction {
    if (state.searchOpen) {
        return 'close-search';
    }

    // Ahead of the detail window because the caret is in the box, behind
    // `close-search` because the caret stays there while the dropdown is open —
    // testing the text first would empty it on an Escape meant for the dropdown.
    if (state.targetIsSearch && state.searchHasText) {
        return 'clear-search';
    }

    if (state.detailOpen) {
        return 'close-detail';
    }

    return 'close-dialog';
}
