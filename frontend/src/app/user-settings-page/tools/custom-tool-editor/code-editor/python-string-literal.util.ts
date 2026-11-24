// C1 controls and the Unicode line/paragraph separators: JSON.stringify leaves them raw, but they are invisible in
// the editor and Monaco treats the separators as unusual line terminators.
const RAW_AFTER_JSON_STRINGIFY = /[\u007f-\u009f\u2028\u2029]/g;

/**
 * Turns text into a double-quoted Python string literal, so it can be inserted into Python source as data and can
 * never end the literal early. JSON.stringify's escapes (\" \\ \n \t \uXXXX) are all valid Python escapes.
 *
 *  pythonStringLiteral('plain')   → '"plain"'
 *  pythonStringLiteral('a"b')     → '"a\\"b"'
 *  pythonStringLiteral('a\nb')    → '"a\\nb"'
 */
export function pythonStringLiteral(text: string): string {
    return JSON.stringify(text).replace(
        RAW_AFTER_JSON_STRINGIFY,
        (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
    );
}
