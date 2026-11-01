'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web6/form-we10le.html'), 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const elements = Object.fromEntries(['username', 'password', 'hash', 'error', 'password-status'].map(
    id => [id, {value: '', textContent: '', focus() {}}]));
const context = vm.createContext({document: {getElementById(id) {return elements[id];}}});
vm.runInContext(fs.readFileSync(path.join(root, 'web6/md5.js'), 'utf8'), context);
vm.runInContext(script, context);

// These expected mappings come from the game's twelve pad input symbols.
const buttons = [
    ['up', 'A', '↑ · A'], ['down', 'B', '↓ · B'],
    ['left', 'C', '← · C'], ['right', 'D', '→ · D'],
    ['l1', 'E', 'L1 · E'], ['l2', 'F', 'L2 · F'],
    ['r1', 'G', 'R1 · G'], ['r2', 'H', 'R2 · H'],
    ['circle', 'I', '○ · I'], ['cross', 'J', '× · J'],
    ['triangle', 'K', '△ · K'], ['square', 'L', '□ · L']
];
const controls = Array.from(html.matchAll(
    /<button type="button" onclick="appendPadPassword\('([^']+)'\);">([^<]+)<\/button>/g));
assert.deepEqual(controls.map(match => [match[1], match[2]]),
    buttons.map(([button, , label]) => [button, label]));
for (const [button, value] of buttons) {
    elements.password.value = '';
    elements.hash.value = 'stale-digest';
    assert.equal(vm.runInContext(`appendPadPassword('${button}')`, context), true);
    assert.equal(elements.password.value, value);
    assert.equal(elements.hash.value, '');
}
elements.password.value = '';
for (const [button] of buttons) {
    vm.runInContext(`appendPadPassword('${button}')`, context);
}
assert.equal(elements.password.value, 'ABCDEFGHIJKL');
vm.runInContext('deletePasswordCharacter()', context);
assert.equal(elements.password.value, 'ABCDEFGHIJK');
vm.runInContext('clearPassword()', context);
assert.equal(elements.password.value, '');
assert.equal(elements['password-status'].textContent, '0 / 31');
vm.runInContext('deletePasswordCharacter()', context);
assert.equal(elements.password.value, '');
assert.equal(vm.runInContext("appendPadPassword('toString')", context), false);
elements.password.value = 'A'.repeat(31);
assert.equal(vm.runInContext("appendPadPassword('up')", context), false);
assert.equal(elements.password.value.length, 31);

// Independently calculate the unchanged game's MD5(username + 16 NUL + password).
for (const [name, password] of [['Player01', 'ABCDEFGHIJKL'], ['Abc', 'A'],
    ['A'.repeat(31), 'L'.repeat(31)]]) {
    elements.username.value = name;
    elements.password.value = password;
    assert.equal(vm.runInContext('makeHash()', context), true);
    const expected = crypto.createHash('md5').update(
        Buffer.concat([Buffer.from(name), Buffer.alloc(16), Buffer.from(password)])).digest('hex');
    assert.equal(elements.hash.value, expected);
}
for (const [name, password] of [['ab', 'A'], ['A'.repeat(32), 'A'],
    ['한글계정', 'A'], [' Abc', 'A'], ['Abc', ''], ['Abc', 'A'.repeat(32)],
    ['Abc', 'a'], ['Abc', 'ABC1'], ['Abc', 'ABM'], ['Abc', 'A B'],
    ['Abc', '한글암호'], ['Abc', 'A\nB']]) {
    elements.username.value = name;
    elements.password.value = password;
    elements.hash.value = 'stale-digest';
    assert.equal(vm.runInContext('makeHash()', context), false);
    assert.equal(elements.password.value, password); // Never silently uppercase or trim.
    assert.equal(elements.hash.value, '');
}
assert.match(html, /name="serial" value="SLKA-25153"/);
const passwordInput = html.match(/<input type="password"[^>]*>/)[0];
assert.doesNotMatch(passwordInput, /\bname=/);
assert.match(passwordInput, /minlength="1" maxlength="31" pattern="\[A-L\]\{1,31\}"/);
assert.match(html, /Start.*Select/);
console.log('WE10LE registration form: pad mapping, boundaries, controls, and hash validation passed');
