/**
 * Stands in for the browser's object-URL registry, which jsdom does not implement, and records which object URLs
 * were created and which are still alive, so a spec can assert that nothing leaks and nothing is revoked twice.
 * Call `install()` in `beforeEach` and `restore()` in `afterEach`.
 */
export class FakeObjectUrls {
    readonly created: string[] = [];
    readonly revoked: string[] = [];
    readonly live = new Set<string>();

    private originalCreate: typeof URL.createObjectURL | undefined;
    private originalRevoke: typeof URL.revokeObjectURL | undefined;

    install(): void {
        this.originalCreate = URL.createObjectURL;
        this.originalRevoke = URL.revokeObjectURL;
        URL.createObjectURL = (): string => {
            const objectUrl = `blob:fake-${this.created.length + 1}`;
            this.created.push(objectUrl);
            this.live.add(objectUrl);
            return objectUrl;
        };
        URL.revokeObjectURL = (objectUrl: string): void => {
            this.revoked.push(objectUrl);
            this.live.delete(objectUrl);
        };
    }

    restore(): void {
        URL.createObjectURL = this.originalCreate as typeof URL.createObjectURL;
        URL.revokeObjectURL = this.originalRevoke as typeof URL.revokeObjectURL;
    }
}
