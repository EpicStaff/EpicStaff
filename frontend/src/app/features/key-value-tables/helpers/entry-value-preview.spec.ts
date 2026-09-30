import { KeyValueTableEntryListItem } from '../models/key-value-table.model';
import { copyableValue, editableValue, previewText } from './entry-value-preview';

const ROW: KeyValueTableEntryListItem = {
    id: 1,
    table: 1,
    key: 'k',
    value_preview: '',
    value_truncated: false,
    created_at: '',
    updated_at: '',
    updated_by_session: null,
    updated_by_graph: null,
    updated_by_graph_name: null,
};

describe('previewText', () => {
    it('shows the server preview, with an ellipsis only when the value was cut', () => {
        expect(previewText({ ...ROW, value_preview: '{"a": 1}', value_truncated: false })).toBe('{"a": 1}');
        expect(previewText({ ...ROW, value_preview: '"xxx', value_truncated: true })).toBe('"xxx…');
    });
});

describe('editableValue', () => {
    it('indents JSON by two spaces, strings included', () => {
        expect(editableValue({ plan: 'pro' })).toBe('{\n  "plan": "pro"\n}');
        expect(editableValue('text')).toBe('"text"');
        expect(editableValue(null)).toBe('null');
    });
});

describe('copyableValue', () => {
    it('copies a string as its raw text', () => {
        expect(copyableValue('line "one"\nline two')).toBe('line "one"\nline two');
    });

    it('copies anything else as JSON indented by two spaces', () => {
        expect(copyableValue({ plan: 'pro', tags: [1] })).toBe('{\n  "plan": "pro",\n  "tags": [\n    1\n  ]\n}');
        expect(copyableValue(42)).toBe('42');
        expect(copyableValue(null)).toBe('null');
    });
});
