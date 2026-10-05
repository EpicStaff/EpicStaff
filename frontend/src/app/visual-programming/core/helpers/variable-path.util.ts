/** Whether `path` names a variable inside the one at `parentPath`, at any depth. */
export function isPathUnder(path: string, parentPath: string): boolean {
    return path.startsWith(`${parentPath}.`) || path.startsWith(`${parentPath}[`);
}
