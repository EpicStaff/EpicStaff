import { Component, input, Provider } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { FieldName, MissingReference } from '../../utils/diff';
import { MissingReferenceNoteComponent, ROUTE_DIFF_FIELDS } from './missing-reference-note.component';
import { missingReference, provideChangesTabDiff, shownMissingReferenceNotes } from './missing-reference-note.testing';

/** A panel field with its note under it. */
@Component({
    imports: [MissingReferenceNoteComponent],
    template: '<app-missing-reference-note [fields]="fields()" />',
})
class FieldWithNoteComponent {
    readonly fields = input.required<readonly FieldName[]>();
}

function render(fields: readonly FieldName[], providers: Provider[]): HTMLElement {
    TestBed.configureTestingModule({ providers });
    const fixture = TestBed.createComponent(FieldWithNoteComponent);
    fixture.componentRef.setInput('fields', fields);
    fixture.detectChanges();
    return fixture.nativeElement;
}

function textsShown(fields: readonly FieldName[], references: readonly MissingReference[]): string[] {
    return shownMissingReferenceNotes(render(fields, [provideChangesTabDiff(references)])).map(({ text }) => text);
}

describe('MissingReferenceNoteComponent', () => {
    it.each<{ kind: string; reference: MissingReference; text: string }>([
        {
            kind: 'a Python code secret',
            reference: missingReference('python_code.secret_names', 'DB_PASS'),
            text: 'This version uses the secret DB_PASS; it no longer exists.',
        },
        {
            kind: 'a pre-computation secret',
            reference: missingReference('pre_computation.secret_names', 'PRE_KEY'),
            text: 'This version uses the secret PRE_KEY; it no longer exists.',
        },
        {
            kind: 'a post-computation secret',
            reference: missingReference('post_computation.secret_names', 'POST_KEY'),
            text: 'This version uses the secret POST_KEY; it no longer exists.',
        },
        {
            kind: 'a Telegram bot key secret',
            reference: missingReference('telegram_bot_api_key_secret_id', 'BOT_TOKEN'),
            text: 'This version uses the secret BOT_TOKEN; it no longer exists.',
        },
        {
            kind: 'a Key-Value table',
            reference: missingReference('key_value_table', 'orders'),
            text: 'This version uses the table orders; it no longer exists.',
        },
        {
            kind: 'an agent',
            reference: missingReference('agent_definition', 41),
            text: 'This version uses agent #41; it no longer exists.',
        },
        {
            kind: 'a webhook trigger',
            reference: missingReference('webhook_trigger', 8),
            text: 'This version uses trigger #8; it no longer exists.',
        },
        {
            kind: 'a subflow',
            reference: missingReference('subgraph', 17),
            text: 'This version uses flow #17; it no longer exists.',
        },
        {
            kind: 'a surface',
            reference: missingReference('surface_list', 5),
            text: 'This version uses surface #5; it no longer exists.',
        },
        {
            kind: 'a local surface tool',
            reference: missingReference('inline_surface', 12),
            text: 'This version uses tool #12; it no longer exists.',
        },
        {
            kind: 'a group route',
            reference: missingReference('condition_groups[].next_node', 99, 'condition_groups[name=yes].next_node'),
            text: 'In this version, group yes routes to a node that no longer exists.',
        },
        {
            kind: 'the default route',
            reference: missingReference('default_next_node', 99),
            text: 'In this version, the default route leads to a node that no longer exists.',
        },
        {
            kind: 'the error route',
            reference: missingReference('next_error_node', 99),
            text: 'In this version, the error route leads to a node that no longer exists.',
        },
    ])('names $kind the version used', ({ reference, text }) => {
        expect(textsShown([reference.field as FieldName], [reference])).toEqual([text]);
    });

    it.each<{ kind: string; reference: MissingReference; text: string }>([
        {
            kind: 'secret',
            reference: missingReference('python_code.secret_names', null),
            text: 'This version uses a secret that no longer exists.',
        },
        {
            kind: 'agent',
            reference: missingReference('agent_definition', null),
            text: 'This version uses an agent that no longer exists.',
        },
    ])('says the same without a name or id when the warning had none ($kind)', ({ reference, text }) => {
        expect(textsShown([reference.field as FieldName], [reference])).toEqual([text]);
    });

    it('covers every route of a table with one list of fields, a note per lost route', () => {
        const references = [
            missingReference('condition_groups[].next_node', 3, 'condition_groups[name=high].next_node'),
            missingReference('next_error_node', 4),
        ];

        expect(textsShown(ROUTE_DIFF_FIELDS, references)).toEqual([
            'In this version, group high routes to a node that no longer exists.',
            'In this version, the error route leads to a node that no longer exists.',
        ]);
    });

    it('shows nothing for a field whose reference is not missing, even when another field of the node is', () => {
        expect(textsShown(['subgraph'], [missingReference('agent_definition', 41)])).toEqual([]);
    });

    it('shows nothing without a diff: the Preview tab and the live editor', () => {
        const root = render(['agent_definition'], []);

        expect(shownMissingReferenceNotes(root)).toEqual([]);
    });

    it('renders a stored name as text, never as markup', () => {
        const root = render(
            ['key_value_table'],
            [provideChangesTabDiff([missingReference('key_value_table', '<img src=x onerror=alert(1)>')])]
        );

        expect(shownMissingReferenceNotes(root).map(({ text }) => text)).toEqual([
            'This version uses the table <img src=x onerror=alert(1)>; it no longer exists.',
        ]);
        expect(root.querySelector('img')).toBeNull();
    });
});
