import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { of } from 'rxjs';

import { ToastService } from '../../../../../../../../../services/notifications';
import { CollectionsApiService } from '../../../../../../../../knowledge-sources/services/collections-api.service';
import { AgentsService } from '../../../../../../../../staff/services/staff.service';
import { SurfaceKnowledge } from '../../../../../../../models/surface.model';
import { SurfaceKnowledgeAdvancedComponent } from './surface-knowledge-advanced.component';

const GRAPH_KNOWLEDGE: SurfaceKnowledge[] = [
    { collection: 1, graph_basic_search_config: { prompt: null, k: 10, max_context_tokens: 12000 } },
];

function render(
    knowledge: SurfaceKnowledge[] = [],
    warning = vi.fn()
): ComponentFixture<SurfaceKnowledgeAdvancedComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: CollectionsApiService, useValue: { getRagsByCollectionId: () => of([]) } },
            { provide: AgentsService, useValue: {} },
            { provide: ToastService, useValue: { warning } },
        ],
    });
    TestBed.overrideComponent(SurfaceKnowledgeAdvancedComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(SurfaceKnowledgeAdvancedComponent);
    fixture.componentRef.setInput('collections', [
        { id: 1, name: 'First' },
        { id: 2, name: 'Second' },
    ]);
    fixture.componentRef.setInput('knowledge', knowledge);
    fixture.detectChanges();
    return fixture;
}

// Stands in for the search_configs group RagTabComponent attaches: every method's subgroup
// is present, but only the selected one is sent.
function attachGraphSearchConfigs(advanced: SurfaceKnowledgeAdvancedComponent): FormGroup {
    const searchConfigs = new FormGroup({
        search_method: new FormControl('basic', [Validators.required]),
        basic: new FormGroup({
            prompt: new FormControl<string | null>(null),
            k: new FormControl(10, [Validators.min(1)]),
            max_context_tokens: new FormControl(12000),
        }),
        drift: new FormGroup({
            prompt: new FormControl<string | null>(null),
            reduce_prompt: new FormControl<string | null>(null),
            n_depth: new FormControl(0, [Validators.min(1)]),
        }),
    });
    advanced.ragTabForm()!.setControl('search_configs', searchConfigs, { emitEvent: false });
    return searchConfigs;
}

describe('SurfaceKnowledgeAdvancedComponent collection switching', () => {
    it('stays on the collection whose settings are invalid', () => {
        const advanced = render().componentInstance;
        advanced.invalidConfig.set(true);

        advanced.selectCollection(2);

        expect(advanced.activeCollectionId()).toBe(1);
    });

    it('switches collection when the settings are valid', () => {
        const advanced = render().componentInstance;

        advanced.selectCollection(2);

        expect(advanced.activeCollectionId()).toBe(2);
    });
});

describe('SurfaceKnowledgeAdvancedComponent graph validity', () => {
    it('ignores an invalid hidden method and emits the selected one', () => {
        const advanced = render(GRAPH_KNOWLEDGE).componentInstance;
        const emitted = vi.fn();
        advanced.knowledgeChange.subscribe(emitted);
        const searchConfigs = attachGraphSearchConfigs(advanced);
        expect(searchConfigs.get('drift')!.invalid).toBe(true);

        advanced.flush();

        expect(advanced.invalidConfig()).toBe(false);
        expect(emitted).toHaveBeenCalledWith(
            expect.objectContaining({
                collection: 1,
                graph_basic_search_config: { prompt: null, k: 10, max_context_tokens: 12000 },
                graph_drift_search_config: null,
            })
        );
    });

    it('refreshes validity on flush without waiting for the debounce', () => {
        const advanced = render(GRAPH_KNOWLEDGE).componentInstance;
        const searchConfigs = attachGraphSearchConfigs(advanced);

        searchConfigs.get('basic.k')!.setValue(0, { emitEvent: false });
        advanced.flush();
        expect(advanced.invalidConfig()).toBe(true);

        searchConfigs.get('basic.k')!.setValue(5, { emitEvent: false });
        advanced.flush();
        expect(advanced.invalidConfig()).toBe(false);
    });

    it('warns when it is destroyed holding invalid settings', () => {
        const warning = vi.fn();
        const fixture = render(GRAPH_KNOWLEDGE, warning);
        const searchConfigs = attachGraphSearchConfigs(fixture.componentInstance);
        searchConfigs.get('basic.k')!.setValue(0, { emitEvent: false });

        fixture.destroy();

        expect(warning).toHaveBeenCalledWith('Invalid retrieval settings were discarded.');
    });
});
