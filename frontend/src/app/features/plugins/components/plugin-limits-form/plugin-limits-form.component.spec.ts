import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of } from 'rxjs';
import type { Mock } from 'vitest';

import { ToastService } from '../../../../services/notifications';
import { PluginLimitsResponse, PluginLimitsUpdate } from '../../models/plugin-backend.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginLimits } from '../../testing/plugin-fixtures';
import { PluginLimitsFormComponent } from './plugin-limits-form.component';

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

    it('shows the limits not enforced yet disabled and labelled', async () => {
        await render();

        for (const key of ['db_connections', 'statement_timeout_seconds', 'requests_per_minute']) {
            expect(row(key).textContent).toContain('Not enforced yet');
            expect(overrideInput(key).disabled).toBe(true);
        }
        expect(row('memory_mb').textContent).not.toContain('Not enforced yet');
        expect(overrideInput('memory_mb').disabled).toBe(false);
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
