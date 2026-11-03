import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const source = readFileSync(new URL("../lib/Folders.js", import.meta.url), "utf8").replace(".pragma library", "");
const F = {};
vm.runInNewContext(source, F);
const plain = v => JSON.parse(JSON.stringify(v));
const scratch = "/tmp/0f8fad5b-d9cb-469f-a165-70867728950e";

test("remember puts the folder first, dedupes and skips scratch folders", () => {
    assert.deepEqual(plain(F.remember(["/a", "/b"], "/b/")), ["/b", "/a"]);
    assert.deepEqual(plain(F.remember(["/a"], scratch)), ["/a"]);
    assert.deepEqual(plain(F.remember(["/a"], "")), ["/a"]);
    const many = Array.from({ length: 10 }, (_, i) => "/d" + i);
    assert.equal(F.remember(many, "/new").length, 8);
});

test("recent folders list launched ones, then sessions newest first", () => {
    const sessions = [
        { cwd: "/old", lastEventAt: 1 },
        { cwd: "/a", lastEventAt: 5 },
        { cwd: scratch, lastEventAt: 9 },
        { cwd: "/new", lastEventAt: 7 },
    ];
    assert.deepEqual(plain(F.recentFolders(["/a"], sessions)), ["/a", "/new", "/old"]);
});

test("items offer a temp folder only without a query", () => {
    assert.deepEqual(plain(F.items(["/home/u/proj"], [], "", "/home/u")), [{ path: "" }, { path: "/home/u/proj" }]);
    assert.deepEqual(plain(F.items(["/home/u/proj", "/srv/x"], [], "pro", "/home/u")), [{ path: "/home/u/proj" }]);
});

test("a typed path lists completions before matching recent folders", () => {
    const items = F.items(["/home/u/proj", "/srv/x"], ["/home/u/pr", "/home/u/proj"], "~/pr", "/home/u");
    assert.deepEqual(plain(items), [{ path: "/home/u/pr" }, { path: "/home/u/proj" }]);
});

test("expand and shorten the home folder", () => {
    assert.equal(F.expand("~/x/", "/home/u"), "/home/u/x");
    assert.equal(F.expand("~", "/home/u"), "/home/u");
    assert.equal(F.shorten("/home/u/x", "/home/u"), "~/x");
    assert.equal(F.shorten("/home/user2", "/home/u"), "/home/user2");
    assert.equal(F.folderName("/home/u/proj/"), "proj");
    assert.equal(F.folderName("/"), "/");
});
