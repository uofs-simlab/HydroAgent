// Minimal parent/iframe DOM for exercising the actual generated resizer script.
function check(condition, message) { if (!condition) throw new Error(message); }
class Target {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, callback, options = {}) {
        if (options.signal && options.signal.aborted) return;
        const item = {callback, once: options.once};
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(item);
        if (options.signal) options.signal.addEventListener('abort', () => this.listeners.get(type).delete(item));
    }
    fire(type, event = {}) {
        for (const item of Array.from(this.listeners.get(type) || [])) {
            item.callback(event);
            if (item.once) this.listeners.get(type).delete(item);
        }
    }
    count() { return Array.from(this.listeners.values()).reduce((n, items) => n + items.size, 0); }
}
class Controller {
    constructor() { this.signal = new Target(); this.signal.aborted = false; }
    abort() { this.signal.aborted = true; this.signal.fire('abort'); }
}
class Element extends Target {
    constructor(testId, width = 300) {
        super(); this.testId = testId; this.width = width;
        this.children = []; this.dataset = {}; this.attributes = {};
        this.classList = {add() {}, remove() {}};
        this.style = {setProperty() {}, removeProperty() {}};
    }
    getAttribute(name) { return name === 'data-testid' ? this.testId : this.attributes[name]; }
    setAttribute(name, value) { this.attributes[name] = value; }
    appendChild(child) { child.parentElement = this; this.children.push(child); }
    querySelector() { return this.children.find(child => child.className === 'sym-assistant-resize-handle'); }
    getBoundingClientRect() { return {width: this.width}; }
    remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
    setPointerCapture() {}
    hasPointerCapture() { return false; }
}
const doc = new Target();
doc.body = new Element('body');
doc.createElement = () => new Element('div');
const row = new Element('stHorizontalBlock', 1200);
const main = new Element('stColumn', 750);
const toggle = new Element('stColumn', 28);
const assistant = new Element('stColumn', 400);
row.appendChild(main); row.appendChild(toggle); row.appendChild(assistant);
doc.querySelectorAll = selector => selector === '.sym-assistant-resize-handle' ? toggle.children.slice() : [];
const host = new Target();
host.document = doc; host.AbortController = Controller;
host.getComputedStyle = () => ({columnGap: '0'});
host.sessionStorage = {getItem() { return null; }, setItem() {}};
const frames = new Map();
host.requestAnimationFrame = callback => { const id = frames.size + 1; frames.set(id, callback); return id; };
host.cancelAnimationFrame = id => frames.delete(id);
function iframe(attached = true) {
    const frame = new Target(); frame.parent = host;
    frame.frameElement = new Element('iframe');
    if (attached) frame.frameElement.parentElement = toggle;
    frame.timers = new Map();
    frame.setTimeout = callback => { const id = frame.timers.size + 1; frame.timers.set(id, callback); return id; };
    frame.clearTimeout = id => frame.timers.delete(id);
    return frame;
}
function install(frame) { new Function('window', resizerSource)(frame); }
let first = iframe();
install(first);
check(doc.count() === 3 && host.count() === 2, 'initial listeners missing');
const oldHandle = toggle.querySelector();
oldHandle.fire('pointerdown', {button: 0, pointerId: 1, clientX: 500, preventDefault() {}});
doc.fire('pointermove', {buttons: 1, pointerId: 1, clientX: 450});
check(frames.size === 1, 'drag should schedule an animation frame');
let second = iframe();
install(second);
check(frames.size === 0, 'reinstall must cancel the old drag frame');
check(doc.count() === 3 && host.count() === 2, 'reinstall leaked parent listeners');
check(oldHandle.count() === 0 && !toggle.children.includes(oldHandle), 'old handle still active');
first.fire('beforeunload');
check(doc.count() === 3 && host.count() === 2, 'old iframe unloaded the replacement');
for (const cleanupSource of cleanupSources) {
    new Function('window', cleanupSource)(second);
    check(doc.count() === 0 && host.count() === 0, 'page cleanup left parent listeners');
    check(toggle.children.length === 0, 'page cleanup left the handle');
    second = iframe(); install(second);
}
second.fire('beforeunload');
check(doc.count() === 0 && host.count() === 0, 'iframe unload leaked listeners');
const waiting = iframe(false);
install(waiting);
check(waiting.timers.size === 1, 'missing retry');
waiting.fire('beforeunload');
check(waiting.timers.size === 0, 'unloaded iframe still has install retry');
check(!host.__hydroagentAssistantResizeCleanup, 'cleanup registration survived disposal');
