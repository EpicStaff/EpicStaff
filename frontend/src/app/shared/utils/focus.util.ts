/**
 * True when nothing on the page has the focus — typically because the focused element was removed and the focus fell
 * to `<body>`. A component recovering the focus after a removal checks this first, so it never takes the focus from
 * whatever the user (or a dialog closing) moved it to. Pass the injected `DOCUMENT`.
 */
export function isFocusLost(document: Document): boolean {
    const active = document.activeElement;
    return !active || active === document.body;
}
