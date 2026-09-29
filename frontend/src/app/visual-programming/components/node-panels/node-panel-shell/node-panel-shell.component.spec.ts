import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { ToastService } from '../../../../services/notifications';
import { NodeModel } from '../../../core/models/node.model';
import { SidePanelService } from '../../../services/side-panel.service';
import { NodePanelShellComponent } from './node-panel-shell.component';

describe('NodePanelShellComponent', () => {
    const shellFor = (type: NodeType): NodePanelShellComponent => {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: SidePanelService,
                    useValue: { autosaveTrigger: signal(0), expandRequest: signal(false), clearExpandRequest: vi.fn() },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        TestBed.overrideComponent(NodePanelShellComponent, { set: { template: '' } });
        const fixture = TestBed.createComponent(NodePanelShellComponent);
        fixture.componentRef.setInput('node', { id: 'node-1', type, node_name: 'Node' } as unknown as NodeModel);
        fixture.detectChanges();
        return fixture.componentInstance;
    };

    it('has no expand button for a key-value node, as for a schedule trigger', () => {
        for (const type of [NodeType.KEY_VALUE, NodeType.SCHEDULE_TRIGGER]) {
            expect(shellFor(type).shouldShowExpandButton()).toBe(false);
            TestBed.resetTestingModule();
        }
        expect(shellFor(NodeType.PYTHON).shouldShowExpandButton()).toBe(true);
    });
});
