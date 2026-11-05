import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const source = readFileSync(new URL("../lib/LaunchOptions.js", import.meta.url), "utf8").replace(".pragma library", "");
const L = {};
vm.runInNewContext(source, L);
const plain = v => JSON.parse(JSON.stringify(v));

test("defaults are default model and medium effort", () => {
    assert.equal(L.DEFAULT_MODEL, "default");
    assert.equal(L.DEFAULT_EFFORT, "medium");
});

test("extra models are appended once, split on commas or whitespace", () => {
    assert.deepEqual(plain(L.models("")), plain(L.MODELS));
    assert.deepEqual(plain(L.models("opus, claude-x\nopusplan")).slice(L.MODELS.length), ["claude-x", "opusplan"]);
});

test("cycle wraps both ways and recovers from unknown values", () => {
    assert.equal(L.cycle(L.EFFORTS, "max", 1), "low");
    assert.equal(L.cycle(L.EFFORTS, "low", -1), "max");
    assert.equal(L.cycle(L.EFFORTS, "nope", 1), "low");
    assert.equal(L.pick(L.EFFORTS, "nope", "medium"), "medium");
});
