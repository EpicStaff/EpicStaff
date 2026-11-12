import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { GraphRagTabbedViewComponent } from './graph-rag-tabbed-view.component';

@Component({
    template: `<app-graph-rag-tabbed-view [ragId]="42">
        <p class="projected">Config content</p>
    </app-graph-rag-tabbed-view>`,
    imports: [GraphRagTabbedViewComponent],
})
class TestHostComponent {}

describe('GraphRagTabbedViewComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;

    function getTabbedView(): GraphRagTabbedViewComponent {
        return fixture.debugElement.query(By.directive(GraphRagTabbedViewComponent))
            .componentInstance as GraphRagTabbedViewComponent;
    }

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [TestHostComponent],
        }).compileComponents();

        fixture = TestBed.createComponent(TestHostComponent);
        fixture.detectChanges();
    });

    it('defaults activeTab to configuration', () => {
        expect(getTabbedView().activeTab()).toBe('configuration');
    });

    it('switches active tab via onTabChange', () => {
        const component = getTabbedView();

        component.onTabChange('visualization');
        expect(component.activeTab()).toBe('visualization');

        component.onTabChange('data-tables');
        expect(component.activeTab()).toBe('data-tables');

        component.onTabChange('configuration');
        expect(component.activeTab()).toBe('configuration');
    });

    it('resets tab to configuration via resetTab', () => {
        const component = getTabbedView();
        component.onTabChange('data-tables');

        component.resetTab();

        expect(component.activeTab()).toBe('configuration');
    });
});
