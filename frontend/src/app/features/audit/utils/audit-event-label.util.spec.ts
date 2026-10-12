import { AuditSessionEvent } from '../models/audit-session.models';
import { auditEventLabel, auditNameLabel, auditRunTypeLabel } from './audit-event-label.util';

function event(overrides: Partial<AuditSessionEvent>): AuditSessionEvent {
    return {
        id: 'id',
        parent_id: '',
        session_id: 1,
        session_message_id: null,
        kind: 'event',
        status: null,
        name: '',
        flow_name: '',
        node_type: '',
        run_type: '',
        input: null,
        output: null,
        error: null,
        details: {},
        event_time: '',
        record_time: null,
        ord_id: 0,
        filter_matched: true,
        ...overrides,
    };
}

describe('auditEventLabel', () => {
    it('maps a known message type', () => {
        expect(auditEventLabel(event({ details: { message_type: 'python_stream' } }))).toBe('Stream');
    });

    it('humanizes an unknown message type', () => {
        expect(auditEventLabel(event({ details: { message_type: 'some_new_type' } }))).toBe('Some new type');
    });

    it('returns null for a missing or blank message type', () => {
        expect(auditEventLabel(event({ details: {} }))).toBeNull();
        expect(auditEventLabel(event({ details: { message_type: '  ' } }))).toBeNull();
    });

    it('returns null for a non-event row', () => {
        expect(auditEventLabel(event({ kind: 'node', details: { message_type: 'start' } }))).toBeNull();
    });
});

describe('auditNameLabel', () => {
    it('drops the label when the name already contains it', () => {
        const sessionStart = event({ name: 'Session Start', details: { message_type: 'session_start' } });
        expect(auditNameLabel(sessionStart)).toBeNull();
    });

    it('gives a session row no name label', () => {
        expect(auditNameLabel(event({ kind: 'session', run_type: 'manual' }))).toBeNull();
    });
});

describe('auditRunTypeLabel', () => {
    it('labels known and unknown run types', () => {
        expect(auditRunTypeLabel('manual')).toBe('Manual');
        expect(auditRunTypeLabel('parent_flow')).toBe('Parent flow');
        expect(auditRunTypeLabel('api_call')).toBe('Api call');
        expect(auditRunTypeLabel('')).toBeNull();
    });
});
