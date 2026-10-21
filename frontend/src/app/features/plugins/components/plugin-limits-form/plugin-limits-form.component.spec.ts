import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of } from 'rxjs';
import type { Mock } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginLimitsResponse, PluginLimitsUpdate } from '../../models/plugin-backend.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginLimits } from '../../testing/plugin-fixtures';
import { NO_DATABASE_BADGE, NOT_ENFORCED_BADGE, PluginLimitsFormComponent } from './plugin-limits-form.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PluginLimitsFormComponent', () => {
    let fixture: ComponentFixture<PluginLimitsFormComponent>;
    let element: HTMLElement;
    let storage: {
        getLimits: Mock<(identifier: string) => Observable<PluginLimitsResponse>>;
        updateLimits: Mock<(identifier: string, update: PluginLimitsUpdate) => Observable<PluginLimitsResponse>>;
    };

    async function render(limits: PluginLimitsResponse = buildPluginLimits()): Promise<void> {
        storage.getLimits.mockReturnValue(of(limits));
        fixture = TestBed.createComponent(PluginLimitsFormComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('identifier', 'weather');
        await settle();
    }

    async function settle(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function row(key: string): HTMLTableRowElement {
        return element.querySelector<HTMLTableRowElement>(`tr[data-limit-key="${key}"]`)!;
    }

    function cellTexts(key: string): string[] {
        return Array.from(row(key).querySelectorAll('td')).map((cell) => cell.textContent?.trim() ?? '');
    }

    function overrideInput(key: string): HTMLInputElement {
        return row(key).querySelector<HTMLInputElement>('app-input-number input')!;
    }

    function buttonIn(container: Element, text: string): HTMLButtonElement | undefined {
        return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim() === text
        );
    }

    function saveButton(): HTMLButtonElement {
        return buttonIn(element.querySelector('.limits__footer')!, 'Save limits')!;
    }

    async function typeOverride(key: string, value: string): Promise<void> {
        const input = overrideInput(key);
        input.value = value;
        input.dispatchEvent(new Event('input'));
        await settle();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        storage = {
            getLimits: vi.fn(() => of(buildPluginLimits())),
            updateLimits: vi.fn(() => of(buildPluginLimits())),
        };
        TestBed.configureTestingModule({
            imports: [PluginLimitsFormComponent],
            providers: [
                { provide: PluginsAdminStorageService, useValue: storage },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('shows for each limit what is requested, the platform maximum and what is in effect', async () => {
        await render();

        expect(storage.getLimits).toHaveBeenCalledWith('weather');
        const memory = cellTexts('memory_mb');
        expect([memory[0], memory[1], memory[3]]).toEqual(['256 MB', '1024 MB', '256 MB']);
        expect(cellTexts('cpu_priority')[0]).toBe('Normal');
        expect(saveButton().disabled).toBe(true);
    });

    it('bounds an override by min(requested, platform maximum)', async () => {
        await render();

        expect(overrideInput('memory_mb').getAttribute('aria-label')).toContain('at most 256');
        await typeOverride('memory_mb', '300');

        const message = row('memory_mb').querySelector('app-input-number small');
        expect(message?.textContent?.trim()).toBe('Enter a whole number from 1 to 256.');
        expect(overrideInput('memory_mb').getAttribute('aria-describedby')).toBe(message?.id);
        expect(saveButton().disabled).toBe(true);

        await typeOverride('memory_mb', '128');
        saveButton().click();

        expect(storage.updateLimits).toHaveBeenCalledWith('weather', { overrides: { memory_mb: 128 } });
    });

    it('removes a stored override with Reset, sending null', async () => {
        await render(
            buildPluginLimits({
                overrides: { memory_mb: 128 },
                effective: { ...buildPluginLimits().effective, memory_mb: 128 },
            })
        );
        expect(overrideInput('memory_mb').value).toBe('128');

        buttonIn(row('memory_mb'), 'Reset')!.click();
        await settle();
        saveButton().click();

        expect(storage.updateLimits).toHaveBeenCalledWith('weather', { overrides: { memory_mb: null } });
    });

    function badge(key: string): string | null {
        return row(key).querySelector('app-plugin-badge')?.textContent?.trim() ?? null;
    }

    /** Weather 0.5.0: it has a database, so the server applies every limit. */
    function withDatabase(): PluginLimitsResponse {
        const limits = buildPluginLimits();
        return {
            ...limits,
            enforced: { ...limits.enforced, db_connections: true, statement_timeout_seconds: true },
            has_database: true,
        };
    }

    it('disables the database limits of a plugin without a database, saying it has none', async () => {
        await render();

        for (const key of ['db_connections', 'statement_timeout_seconds']) {
            expect(badge(key)).toBe(NO_DATABASE_BADGE);
            expect(NO_DATABASE_BADGE).toBe('No database');
            expect(overrideInput(key).disabled).toBe(true);
        }
        for (const key of ['memory_mb', 'requests_per_minute', 'cpu_priority']) {
            expect(badge(key)).toBeNull();
        }
        expect(overrideInput('memory_mb').disabled).toBe(false);
        expect(overrideInput('requests_per_minute').disabled).toBe(false);
    });

    it('lets the database limits be lowered for a plugin with a database', async () => {
        await render(withDatabase());

        for (const key of ['db_connections', 'statement_timeout_seconds']) {
            expect(badge(key)).toBeNull();
            expect(overrideInput(key).disabled).toBe(false);
        }
        await typeOverride('db_connections', '2');
        saveButton().click();

        expect(storage.updateLimits).toHaveBeenCalledWith('weather', { overrides: { db_connections: 2 } });
    });

    it('explains under the statement timeout that the plugin can change it and EpicStaff restores it', async () => {
        await render(withDatabase());

        expect(row('statement_timeout_seconds').querySelector('.limits__hint')?.textContent?.trim()).toBe(
            'A default the plugin can change for its own sessions; EpicStaff restores it within a minute.'
        );
        expect(element.querySelectorAll('.limits__hint')).toHaveLength(1);
    });

    it('disables any other limit the server does not apply, labelled as not enforced', async () => {
        const limits = withDatabase();
        await render({ ...limits, enforced: { ...limits.enforced, requests_per_minute: false } });

        expect(badge('requests_per_minute')).toBe(NOT_ENFORCED_BADGE);
        expect(overrideInput('requests_per_minute').disabled).toBe(true);
        expect(badge('db_connections')).toBeNull();
    });

    it('offers only "low" as a CPU override, and not when the plugin asks for low itself', async () => {
        await render();

        row('cpu_priority').querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        await settle();
        saveButton().click();

        expect(storage.updateLimits).toHaveBeenCalledWith('weather', { overrides: { cpu_priority: 'low' } });

        fixture.destroy();
        const lowRequested = buildPluginLimits();
        lowRequested.requested.cpu_priority = 'low';
        await render(lowRequested);

        expect(row('cpu_priority').querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true);
    });
});
