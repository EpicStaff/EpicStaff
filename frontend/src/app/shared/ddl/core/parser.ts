import type { ClassDecl, DomainDecl, Literal, Program, Property, TypeNode } from './ast';
import { type Diagnostic, type Span, error } from './diagnostics';
import type { Token, TokenType } from './lexer';

class Parser {
    private pos = 0;
    readonly diagnostics: Diagnostic[] = [];

    constructor(private readonly tokens: Token[]) {}

    private peek(offset = 0): Token {
        return this.tokens[Math.min(this.pos + offset, this.tokens.length - 1)]!;
    }

    private next(): Token {
        const t = this.peek();
        if (this.pos < this.tokens.length - 1) this.pos++;
        return t;
    }

    private at(type: TokenType): boolean {
        return this.peek().type === type;
    }

    private expect(type: TokenType, what: string): Token | undefined {
        if (this.at(type)) return this.next();
        this.diagnostics.push(
            error('expected', `Expected ${what}, but found '${this.describe(this.peek())}'.`, this.peek().span)
        );
        return undefined;
    }

    private describe(t: Token): string {
        if (t.type === 'newline') return 'end of line';
        if (t.type === 'eof') return 'end of file';
        if (t.type === 'indent' || t.type === 'dedent') return 'indentation change';
        return t.value || t.type;
    }

    /** Skip forward to the next line so one error doesn't cascade. */
    private recoverLine(): void {
        while (!this.at('newline') && !this.at('eof')) this.next();
        if (this.at('newline')) this.next();
    }

    parse(): Program {
        const classes: ClassDecl[] = [];
        let domain: DomainDecl | undefined;

        while (!this.at('eof')) {
            if (this.at('newline')) {
                this.next();
                continue;
            }
            if (this.at('class')) {
                const c = this.parseClass();
                if (c) classes.push(c);
            } else if (this.at('domain')) {
                const d = this.parseDomain();
                if (d) {
                    if (domain) {
                        this.diagnostics.push(error('duplicate-domain', "Only one 'domain' block is allowed.", d.span));
                    } else {
                        domain = d;
                    }
                }
            } else {
                this.diagnostics.push(
                    error(
                        'unexpected-top-level',
                        `Expected 'class' or 'domain' at the start of a declaration, found '${this.describe(this.peek())}'.`,
                        this.peek().span
                    )
                );
                this.recoverLine();
            }
        }

        return { classes, domain };
    }

    private parseClass(): ClassDecl | undefined {
        const kw = this.next(); // 'class'
        const nameTok = this.expect('ident', 'a class name');
        if (!nameTok) {
            this.recoverLine();
            return undefined;
        }

        let base: string | undefined;
        let baseSpan: Span | undefined;

        // Inheritance is written `is a Base` (also `is an Base` / `is Base`).
        if (this.at('ident') && this.peek().value === 'is') {
            this.next(); // 'is'
            if (this.at('ident') && (this.peek().value === 'a' || this.peek().value === 'an')) {
                this.next(); // 'a' | 'an'
            }
            const baseTok = this.expect('ident', "a base class name after 'is a'");
            if (baseTok) {
                base = baseTok.value;
                baseSpan = baseTok.span;
            }
        } else if (this.at('colon')) {
            // Old syntax `class X : Base`: accept it but nudge toward `is a`.
            const colon = this.next();
            const baseTok = this.expect('ident', 'a base class name');
            if (baseTok) {
                base = baseTok.value;
                baseSpan = baseTok.span;
            }
            this.diagnostics.push(
                error(
                    'colon-inheritance',
                    `Use 'is a' for inheritance, e.g. \`class ${nameTok.value} is a ${base ?? 'Base'}\`.`,
                    { start: colon.span.start, end: (baseTok ?? colon).span.end }
                )
            );
        }

        this.expect('newline', 'end of line');
        const properties = this.parseBlock();

        return {
            kind: 'class',
            name: nameTok.value,
            nameSpan: nameTok.span,
            base,
            baseSpan,
            properties,
            span: { start: kw.span.start, end: nameTok.span.end },
        };
    }

    private parseDomain(): DomainDecl {
        const kw = this.next(); // 'domain'
        // Allow an optional name/colon noise on the header line, then require newline.
        this.expect('newline', "end of line after 'domain'");
        const fields = this.parseBlock();
        return { kind: 'domain', fields, span: kw.span };
    }

    /** Parse an indented block of `name: Type [= default]` lines. */
    private parseBlock(): Property[] {
        const props: Property[] = [];
        if (!this.at('indent')) {
            this.diagnostics.push(error('empty-block', 'Expected an indented block of properties.', this.peek().span));
            return props;
        }
        this.next(); // indent

        while (!this.at('dedent') && !this.at('eof')) {
            if (this.at('newline')) {
                this.next();
                continue;
            }
            const prop = this.parseProperty();
            if (prop) props.push(prop);
            else this.recoverLine();
        }
        if (this.at('dedent')) this.next();
        return props;
    }

    private parseProperty(): Property | undefined {
        const nameTok = this.expect('ident', 'a property name');
        if (!nameTok) return undefined;
        if (!this.expect('colon', "':' after the property name")) return undefined;

        const type = this.parseType();
        if (!type) return undefined;

        let def: Literal | undefined;
        if (this.at('equals')) {
            this.next();
            def = this.parseLiteral();
        }

        this.expect('newline', 'end of line');
        return {
            name: nameTok.value,
            type,
            default: def,
            span: { start: nameTok.span.start, end: type.span.end },
        };
    }

    /** typeExpr := ( "[" typeExpr "]" | Ident ) "?"? */
    private parseType(): TypeNode | undefined {
        let node: TypeNode | undefined;

        if (this.at('lbracket')) {
            const open = this.next();
            const element = this.parseType();
            if (!element) return undefined;
            const close = this.expect('rbracket', "']' to close the list type");
            node = {
                kind: 'list',
                element,
                span: { start: open.span.start, end: (close ?? element).span.end },
            };
        } else if (this.at('ident')) {
            const t = this.next();
            node = { kind: 'named', name: t.value, span: t.span };
        } else {
            this.diagnostics.push(
                error('expected-type', `Expected a type name, found '${this.describe(this.peek())}'.`, this.peek().span)
            );
            return undefined;
        }

        if (this.at('question')) {
            const q = this.next();
            node = { kind: 'optional', inner: node, span: { start: node.span.start, end: q.span.end } };
        }
        return node;
    }

    private parseLiteral(): Literal | undefined {
        const t = this.peek();
        switch (t.type) {
            case 'int':
                this.next();
                return { kind: 'int', value: Number(t.value), span: t.span };
            case 'float':
                this.next();
                return { kind: 'float', value: Number(t.value), span: t.span };
            case 'string':
                this.next();
                return { kind: 'string', value: t.value, span: t.span };
            case 'bool':
                this.next();
                return { kind: 'bool', value: t.value === 'true', span: t.span };
            case 'null':
                this.next();
                return { kind: 'null', value: null, span: t.span };
            default:
                this.diagnostics.push(
                    error('expected-literal', `Expected a default value, found '${this.describe(t)}'.`, t.span)
                );
                return undefined;
        }
    }
}

export function parse(tokens: Token[]): { program: Program; diagnostics: Diagnostic[] } {
    const p = new Parser(tokens);
    const program = p.parse();
    return { program, diagnostics: p.diagnostics };
}
