/** Creates an element with a class and text. Text only: nothing here is ever parsed as HTML. */
export function element<Tag extends keyof HTMLElementTagNameMap>(
    tag: Tag,
    className: string | null,
    text?: string
): HTMLElementTagNameMap[Tag] {
    const created = document.createElement(tag);
    if (className) created.className = className;
    if (text !== undefined) created.textContent = text;
    return created;
}

/** A definition list of label and value pairs. */
export function facts(entries: readonly (readonly [string, string])[]): HTMLDListElement {
    const list = element('dl', 'facts');
    for (const [label, value] of entries) {
        list.append(element('dt', null, label), element('dd', null, value));
    }
    return list;
}
