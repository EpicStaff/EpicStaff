import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { GraphSessionStatus } from '@shared/models';
import { of } from 'rxjs';

import {
    GraphSessionLight,
    GraphSessionService,
    SessionTrigger,
} from '../../../../features/flows/services/flows-sessions.service';
import { RunGraphPageService } from '../../services/run-graph-page.service';
import { MemoryService } from '../memory-sidebar/service/memory.service';
import { RunningGraphHeaderComponent } from './run-graph-header.component';

function session(id: number, trigger: SessionTrigger | null): GraphSessionLight {
    return {
        id,
        graph_id: 3,
        graph_name: 'Orders',
        status: GraphSessionStatus.ENDED,
        status_updated_at: '2026-10-01T10:00:00Z',
        created_at: '2026-10-01T10:00:00Z',
        finished_at: '2026-10-01T10:01:00Z',
        trigger,
    };
}

function telegramTrigger(isTestRun: boolean): SessionTrigger {
    return { trigger_type: 'telegram', trigger_id: 1, is_test_run: isTestRun };
}

function createFixture(sessionId: string): ComponentFixture<RunningGraphHeaderComponent> {
    const fixture = TestBed.createComponent(RunningGraphHeaderComponent);
    fixture.componentRef.setInput('graphId', 3);
    fixture.componentRef.setInput('sessionId', sessionId);
    fixture.detectChanges();
    return fixture;
}

function typeValue(fixture: ComponentFixture<RunningGraphHeaderComponent>): string | undefined {
    return (fixture.nativeElement as HTMLElement)
        .querySelector('.session-meta-item .session-meta-item__value')
        ?.textContent?.trim();
}

describe('RunningGraphHeaderComponent session type', () => {
    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                { provide: Dialog, useValue: {} },
                { provide: MemoryService, useValue: {} },
                { provide: RunGraphPageService, useValue: { getMemories: () => [] } },
                {
                    provide: GraphSessionService,
                    useValue: {
                        getSessionsByGraphId: () =>
                            of({
                                results: [
                                    session(3, telegramTrigger(true)),
                                    session(2, telegramTrigger(false)),
                                    session(1, null),
                                ],
                            }),
                    },
                },
            ],
        });
        // The sidebar, files button and switcher bring their own services; only the meta row is under test.
        TestBed.overrideComponent(RunningGraphHeaderComponent, {
            set: { imports: [DatePipe], schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
    });

    it('shows Test for a test run and keeps the trigger chip without a test marker', () => {
        const fixture = createFixture('3');
        const element = fixture.nativeElement as HTMLElement;

        expect(typeValue(fixture)).toBe('Test');
        expect(element.querySelector('.trigger-chip')?.textContent?.trim()).toBe('Telegram');
        expect(element.querySelector('.session-meta-row app-test-run-chip')).toBeNull();
    });

    it('shows Live for a live run', () => {
        expect(typeValue(createFixture('2'))).toBe('Live');
    });

    it('shows Live for a session without a trigger', () => {
        expect(typeValue(createFixture('1'))).toBe('Live');
    });

    it('shows no type until the current session is loaded', () => {
        expect(typeValue(createFixture('99'))).toBe('');
    });
});
