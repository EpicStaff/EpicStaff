import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ToggleSwitchComponent } from '@shared/components';

import { NodeStorageSectionComponent } from './node-storage-section.component';

describe('NodeStorageSectionComponent lock reason', () => {
    let fixture: ComponentFixture<NodeStorageSectionComponent>;

    function render(inputs: { lockReason?: string | null; readonly?: boolean }): void {
        fixture = TestBed.createComponent(NodeStorageSectionComponent);
        fixture.componentRef.setInput('useStorage', false);
        fixture.componentRef.setInput('lockReason', inputs.lockReason ?? null);
        fixture.componentRef.setInput('readonly', inputs.readonly ?? false);
        fixture.detectChanges();
    }

    function switchDisabled(): boolean {
        return fixture.debugElement.query(By.directive(ToggleSwitchComponent)).componentInstance.disabled();
    }

    function hint(): string | null {
        const element = (fixture.nativeElement as HTMLElement).querySelector('app-hint-message');
        return element ? (element.textContent ?? '').trim() : null;
    }

    it('disables the switch and shows the reason under it', () => {
        render({ lockReason: 'Storage needs Files: Read.' });

        expect(switchDisabled()).toBe(true);
        expect(hint()).toBe('Storage needs Files: Read.');
    });

    it('leaves the switch enabled and shows no hint without a reason', () => {
        render({});

        expect(switchDisabled()).toBe(false);
        expect(hint()).toBeNull();
    });

    it('shows no hint when the section is read-only anyway, but keeps the switch disabled', () => {
        render({ lockReason: 'Storage needs Files: Read.', readonly: true });

        expect(switchDisabled()).toBe(true);
        expect(hint()).toBeNull();
    });
});
