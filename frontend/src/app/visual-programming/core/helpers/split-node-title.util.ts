export function splitNodeTitleBadge(
    name: string,
    nodeNumber: number | null | undefined
): { label: string; badge: string | null } {
    if (nodeNumber == null) return { label: name, badge: null };

    const badge = `#${nodeNumber}`;
    const suffix = ` ${badge}`;
    if (!name.endsWith(suffix)) return { label: name, badge: null };

    return { label: name.slice(0, -suffix.length), badge };
}
